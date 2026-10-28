
"""Part 1: static-cost Dijkstra routing and loop-free flooding.

Link costs are the delays in topology/ceg_mesh_topo.py, represented in the
matching MiniEdit file. 

Traffic monitoring uses OpenFlow statistics to estimate ICMP echo-request
rates and maintain an exponential moving average (EMA) baseline. Traffic
exceeding the configured threshold is flagged as anomalous, and the suspected
source IP is blocked across the switches.

28 October 2026: Added ICMP anomaly detection and source IP blocking.
"""

import heapq
import json
import time
from pathlib import Path

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.lib.packet import packet, ethernet, ether_types, ipv4, icmp
from ryu.ofproto import ofproto_v1_3
from ryu.topology.api import get_switch, get_link


ROOT = Path(__file__).resolve().parents[1]
COOKIE = 0x51010001
BLOCK_COOKIE = 0x51010002

def shortest_path(graph, start, goal):
    """Dijkstra: return (switch list, total cost), or ([], infinity)."""
    queue = [(0, (start,))]
    visited = set()
    while queue:
        cost, path = heapq.heappop(queue)
        node = path[-1]
        if node in visited:
            continue
        visited.add(node)
        if node == goal:
            return list(path), cost
        for neighbor, weight in sorted(graph.get(node, {}).items()):
            if neighbor not in visited:
                heapq.heappush(queue, (cost + weight, path + (neighbor,)))
    return [], float('inf')


def spanning_tree(graph):
    """Prim's algorithm, with deterministic tie-breaking; return tree edges."""
    if not graph:
        return set()
    seen = {min(graph)}
    queue = [(w, min(graph), v) for v, w in graph[min(graph)].items()]
    heapq.heapify(queue)
    tree = set()
    while queue:
        weight, u, v = heapq.heappop(queue)
        if v in seen:
            continue
        seen.add(v)
        tree.add(tuple(sorted((u, v))))
        for nxt, cost in graph[v].items():
            if nxt not in seen:
                heapq.heappush(queue, (cost, v, nxt))
    return tree


class PathController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        topo = json.loads((ROOT / 'topology/assignment_mesh.mn').read_text())
        self.expected_switches = {int(s['opts']['dpid'], 16) for s in topo['switches']}
        self.costs, self.access_ports = {}, {}
        self.expected_ports = {}
        for link in topo['links']:
            a, b, opts = link['src'], link['dest'], link['opts']
            if a.startswith('s') and b.startswith('s'):
                u, v = int(a[1:]), int(b[1:])
                self.costs[tuple(sorted((u, v)))] = float(opts['delay'][:-2])
                self.expected_ports[u, v] = opts['port1']
                self.expected_ports[v, u] = opts['port2']
            else:
                sw, port = (a, opts['port1']) if a.startswith('s') else (b, opts['port2'])
                self.access_ports.setdefault(int(sw[1:]), set()).add(port)
        self.datapaths, self.hosts = {}, {}

        # Q2: traffic monitoring and anomaly detection
        self.alpha = 0.3
        self.threshold_multiplier = 3.0
        # Per-switch flow counters and observation timestamps
        self.last_counts = {}
        self.last_stats_time = {}
        # Per-source-IP traffic measurements and EMA baseline
        self.source_stats = {}
        # Source IPs detected and blocked
        self.blocked_ips = set()

        self.graph, self.ports, self.tree = {}, {}, set()
        self.ready = False
        self.signature = None
        self.logged_routes = set()
        self.state_path = ROOT / 'results/data/topology_state.json'
        self.route_path = ROOT / 'results/logs/routes.jsonl'
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.route_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_state()
        self.monitor = hub.spawn(self._discover)

        self.stats_monitor = hub.spawn(self._monitor_stats)

    def _add_flow(self, dp, priority, match, actions, cookie=COOKIE):
        p, ofp = dp.ofproto_parser, dp.ofproto
        instructions = [p.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(p.OFPFlowMod(datapath=dp, cookie=cookie, priority=priority,
                                match=match, instructions=instructions))

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        p, ofp = dp.ofproto_parser, dp.ofproto
        self._add_flow(dp, 0, p.OFPMatch(),
                       [p.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)], cookie=0)
        self.logger.info('Connected: s%s', dp.id)
        # Apply existing blocks to a newly connected switch.
        for ip_src in self.blocked_ips:
            self._install_block_rule(dp, ip_src)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change(self, ev):
        if ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(ev.datapath.id, None)
        else:
            self.datapaths[ev.datapath.id] = ev.datapath

    # Q2: Traffic monitoring
    def _monitor_stats(self):
        """Periodically request OpenFlow flow statistics."""
        hub.sleep(10)
        while True:
            for dp in list(self.datapaths.values()):
                try:
                    parser = dp.ofproto_parser
                    request = parser.OFPFlowStatsRequest(dp, table_id=0, match=parser.OFPMatch(),)
                    dp.send_msg(request)
                except Exception:
                    self.logger.exception("Failed to request statistics from s%s", dp.id)
            hub.sleep(5)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply(self, ev):
        """Calculate source-IP traffic rates and detect anomalies."""
        dp = ev.msg.datapath
        dpid = dp.id
        now = time.time()
        previous_time = self.last_stats_time.get(dpid)
        self.last_stats_time[dpid] = now
        # The first reply establishes counter values, not a rate sample.
        if previous_time is None:
            elapsed = None
        else:
            elapsed = max(now - previous_time, 0.001)
        previous_counts = self.last_counts.setdefault(dpid, {})
        source_deltas = {}
        for stat in ev.msg.body:
            
            # Count only IPv4 ICMP echo requests, not echo replies.
            if (stat.match.get("eth_type") != 0x0800 or stat.match.get("ip_proto") != 1 or stat.match.get("icmpv4_type") != 8):
                    continue
            
            ip_src = stat.match.get("ipv4_src")
            in_port = stat.match.get("in_port")
            # Count traffic entering from hosts, not traffic transiting
            # intermediate switches. This avoids counting one packet
            # repeatedly as it traverses the network.
            if (not ip_src or in_port not in self.access_ports.get(dpid, set())):
                continue
            # Identify individual flows rather than using the source IP
            # alone as the counter key.
            # flow_key = (in_port, stat.match.get("eth_src"), stat.match.get("eth_dst"), stat.match.get("eth_type"), ip_src, stat.match.get("ipv4_dst"),)

            flow_key = (in_port, stat.match.get("eth_src"), stat.match.get("eth_dst"), stat.match.get("eth_type"), stat.match.get("ip_proto"), stat.match.get("icmpv4_type"), ip_src, stat.match.get("ipv4_dst"),)

            total = stat.packet_count
            previous = previous_counts.get(flow_key)
            previous_counts[flow_key] = total
            # A new flow's existing counter is not a measured interval.
            if previous is None or elapsed is None:
                continue
            delta = max(0, total - previous)
            source_deltas[ip_src] = (source_deltas.get(ip_src, 0) + delta)
        for ip_src, delta in source_deltas.items():
            rate_pps = delta / elapsed
            entry = self.source_stats.get(ip_src)
            if entry is None:
                # Require a non-zero sample to initialize the baseline.
                if rate_pps <= 0:
                    continue
                self.source_stats[ip_src] = {"rate_pps": rate_pps, "baseline": rate_pps,}
                self.logger.info("Q2 BASELINE: IP=%s rate=%.2f pps", ip_src, rate_pps,)
                continue
            baseline = entry["baseline"]
            entry["rate_pps"] = rate_pps
            self.logger.info("Q2 STATS: IP=%s rate=%.2f pps baseline=%.2f pps", ip_src, rate_pps, baseline,)
            # Detect using the previous baseline, before updating the EMA.
            anomalous = (baseline > 0 and rate_pps > self.threshold_multiplier * baseline)
            if anomalous and ip_src not in self.blocked_ips:
                self.logger.warning("Q2 ANOMALY: IP=%s rate=%.2f pps baseline=%.2f pps", ip_src, rate_pps, baseline,)
                self._block_ip(ip_src)
            elif rate_pps > 0 and ip_src not in self.blocked_ips:
                entry["baseline"] = (self.alpha * rate_pps + (1 - self.alpha) * baseline)

    # Q2: Source-IP blocking
    def _install_block_rule(self, dp, ip_src):
        """Install a high-priority drop rule for an IPv4 source."""
        parser = dp.ofproto_parser
        match = parser.OFPMatch(eth_type=0x0800, ipv4_src=ip_src,)
        # Empty actions mean drop the matching packet.
        self._add_flow(dp, 5000,match, [], cookie=BLOCK_COOKIE,)

    def _block_ip(self, ip_src):
        """Block an anomalous source on every connected switch."""
        if ip_src in self.blocked_ips:
            return
        self.blocked_ips.add(ip_src)
        for dp in list(self.datapaths.values()):
            self._install_block_rule(dp, ip_src)
        self.logger.warning("Q2 BLOCKED: IP=%s switches=%d", ip_src, len(self.datapaths),)

    def _clear_routes(self):
        # Delete only this application's forwarding rules, preserving table-miss
        # and any future firewall rules with different cookies.
        for dp in self.datapaths.values():
            p, ofp = dp.ofproto_parser, dp.ofproto
            dp.send_msg(p.OFPFlowMod(datapath=dp, command=ofp.OFPFC_DELETE,
                cookie=COOKIE, cookie_mask=0xffffffffffffffff,
                out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY, match=p.OFPMatch()))
        self.logged_routes.clear()

    def _discover(self):
        """LLDP discovery is supplied by ryu-manager --observe-links."""
        previous = None
        while True:
            try:
                switches = {s.dp.id for s in get_switch(self, None)}
                observed = {(l.src.dpid, l.dst.dpid): (l.src.port_no, l.dst.port_no)
                            for l in get_link(self, None)}
                ports, graph = {}, {s: {} for s in switches}
                for (u, v), cost in self.costs.items():
                    # Require discovery in BOTH directions and validate the ports.
                    if observed.get((u, v)) != (self.expected_ports[u, v], self.expected_ports[v, u]):
                        continue
                    if observed.get((v, u)) != (self.expected_ports[v, u], self.expected_ports[u, v]):
                        continue
                    if u in graph and v in graph:
                        graph[u][v] = graph[v][u] = cost
                        ports[u, v], ports[v, u] = observed[u, v]
                signature = (tuple(sorted(switches)), tuple(sorted(ports.items())))
                complete = switches == self.expected_switches and len(ports) == 2 * len(self.costs)
                ready = complete and signature == previous
                if signature != self.signature or ready != self.ready:
                    self.ready = False
                    self._clear_routes()
                    self.graph, self.ports = graph, ports
                    self.tree = spanning_tree(graph)
                    self.signature, self.ready = signature, ready
                    self.logger.info('Topology: %s switches, %s/11 links; ready=%s',
                                     len(graph), len(ports)//2, ready)
                    self._write_state()
                previous = signature
            except Exception:
                self.ready = False
                self.logger.exception('Topology discovery failed')
                self._write_state()
            hub.sleep(1)

    def _write_state(self):
        path, cost = shortest_path(self.graph, 1, 6)
        state = {'time': time.time(), 'ready': self.ready,
                 'switches': sorted(self.graph),
                 'links': [{'src': u, 'dst': v, 'cost': w,
                            'src_port': self.ports[u, v], 'dst_port': self.ports[v, u]}
                           for u in self.graph for v, w in self.graph[u].items() if u < v],
                 'mst': sorted(self.tree), 's1_to_s6': path,
                 's1_to_s6_cost': cost if path else None}
        temporary = self.state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(self.state_path)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in(self, ev):
        msg, dp = ev.msg, ev.msg.datapath
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        ip_pkt = pkt.get_protocol(ipv4.ipv4)

        if not eth or eth.ethertype == ether_types.ETH_TYPE_LLDP or not self.ready:
            return
        if ip_pkt and ip_pkt.src in self.blocked_ips:
            return
        # This lab measures IPv4; suppress IPv6 background multicast.
        if eth.ethertype == ether_types.ETH_TYPE_IPV6:
            return
        incoming, switch = msg.match['in_port'], dp.id
        access = incoming in self.access_ports.get(switch, set())
        if access:
            self.hosts[eth.src] = (switch, incoming)
        p = dp.ofproto_parser
        if eth.dst not in self.hosts or int(eth.dst[:2], 16) & 1:
            # Flood only on MST edges plus host-facing ports. Ignore packets
            # entering through a non-tree inter-switch port to prevent loops.
            tree_ports = {self.ports[switch, n] for n in self.graph.get(switch, {})
                          if tuple(sorted((switch, n))) in self.tree}
            if not access and incoming not in tree_ports:
                return
            outgoing = (tree_ports | self.access_ports.get(switch, set())) - {incoming}
        else:
            destination, host_port = self.hosts[eth.dst]
            path, cost = shortest_path(self.graph, switch, destination)
            if not path:
                return
            port = host_port if len(path) == 1 else self.ports[path[0], path[1]]
            if port == incoming:
                return
            outgoing = {port}
            # fields = dict(in_port=incoming, eth_src=eth.src, eth_dst=eth.dst,
            #               eth_type=eth.ethertype)
            # self._add_flow(dp, 100, p.OFPMatch(**fields), [p.OFPActionOutput(port)])

            fields = dict(in_port=incoming, eth_src=eth.src, eth_dst=eth.dst, eth_type=eth.ethertype,)
            if ip_pkt:
                fields["ipv4_src"] = ip_pkt.src
                fields["ipv4_dst"] = ip_pkt.dst
                if ip_pkt.proto == 1:
                    icmp_pkt = pkt.get_protocol(icmp.icmp)
                    if icmp_pkt is not None:
                        fields["ip_proto"] = 1
                        fields["icmpv4_type"] = icmp_pkt.type
            self._add_flow( dp, 100, p.OFPMatch(**fields), [p.OFPActionOutput(port)],)

            if access:
                key = (eth.src, eth.dst, tuple(path))
                if key not in self.logged_routes:
                    self.logged_routes.add(key)
                    self.logger.info('Route %s -> %s: %s (cost=%g)', eth.src, eth.dst,
                                     ' -> '.join('s%s' % n for n in path), cost)
                    with self.route_path.open('a') as output:
                        output.write(json.dumps({'time': time.time(), 'src': eth.src,
                            'dst': eth.dst, 'path': path, 'cost': cost}) + '\n')
        if outgoing:
            ofp = dp.ofproto
            dp.send_msg(p.OFPPacketOut(datapath=dp, buffer_id=ofp.OFP_NO_BUFFER,
                in_port=incoming, actions=[p.OFPActionOutput(port) for port in sorted(outgoing)],
                data=msg.data))
