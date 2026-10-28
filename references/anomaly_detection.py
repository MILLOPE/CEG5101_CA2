from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4
from ryu.lib.dpid import dpid_to_str
from ryu.lib import hub
import time
import json


class Assignment3Controller(app_manager.RyuApp):
    """
    Anomaly Detection Controller with flow stat collection and blocking
    """
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(Assignment3Controller, self).__init__(*args, **kwargs)

        self.mac_to_port = {}
        self.datapaths = {}  # active switches
        self.stats = {}      # {dpid: {ip: {'count': int, 'baseline': float}}}
        self.last_counts = {}  # {dpid: {ip: last_total_count}}
        self.blocked_ips = set()
        self.ip_to_mac = {}

        # anomaly detection parameters
        self.alpha = 0.3
        self.threshold_multiplier = 3

        self.state_history = []

        # spawn monitor thread
        self.monitor_thread = hub.spawn(self._monitor)

    # ------------------------------
    # Monitoring & stats collection
    # ------------------------------
    def _monitor(self):
        hub.sleep(10)  # give switches time to connect
        while True:
            for dpid, dp in list(self.datapaths.items()):
                self._request_stats(dp)
            hub.sleep(5)
            self._check_anomalies()
            self._log_state()

    def _request_stats(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        req = parser.OFPFlowStatsRequest(datapath, table_id=0, match=match)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        body = ev.msg.body

        if dpid not in self.stats:
            self.stats[dpid] = {}
        if dpid not in self.last_counts:
            self.last_counts[dpid] = {}

        switch_stats = {}

        for stat in body:
            ip_src = stat.match.get('ipv4_src')
            if not ip_src:
                continue

            total = stat.packet_count
            prev = self.last_counts[dpid].get(ip_src, total)
            delta = max(0, total - prev)

            self.last_counts[dpid][ip_src] = total
            switch_stats[ip_src] = switch_stats.get(ip_src, 0) + delta

        for ip_src, delta in switch_stats.items():
            if ip_src not in self.stats[dpid]:
                self.stats[dpid][ip_src] = {'count': delta, 'baseline': delta}
            else:
                old = self.stats[dpid][ip_src]['baseline']
                new_baseline = self.alpha * delta + (1 - self.alpha) * old
                self.stats[dpid][ip_src] = {'count': delta, 'baseline': new_baseline}

            self.logger.info(
                "Stats update: %s on switch %s → delta=%d, baseline=%.2f",
                ip_src, dpid_to_str(dpid), delta, self.stats[dpid][ip_src]['baseline']
            )

    # ------------------------------
    # Anomaly detection & blocking
    # ------------------------------
    def _check_anomalies(self):
        for dpid, ip_stats in self.stats.items():
            for ip, stats in ip_stats.items():
                current = stats['count']
                baseline = stats['baseline']

                if baseline > 0 and current > self.threshold_multiplier * baseline:
                    if ip not in self.blocked_ips:
                        self.logger.warning(
                            "Anomaly detected: %s on switch %s "
                            "(cur=%d, base=%.2f)",
                            ip, dpid_to_str(dpid), current, baseline
                        )
                        self._block_ip(ip)
                        self.blocked_ips.add(ip)
                        self.state_history.append({
                            'time': time.time(),
                            'event': 'block',
                            'ip': ip,
                            'dpid': dpid_to_str(dpid),
                            'current_pps': current,
                            'baseline_pps': baseline
                        })

    def _block_ip(self, ip):
        for datapath in self.datapaths.values():
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            match = parser.OFPMatch(eth_type=0x0800, ipv4_src=ip)
            actions = []  # drop
            self._add_flow(datapath, 5000, match, actions)  # high-priority drop
        self.logger.info("Blocking IP %s across all switches", ip)

    # ------------------------------
    # State logging
    # ------------------------------
    def _log_state(self):
        state = {
            'time': time.time(),
            'blocked_ips': list(self.blocked_ips),
            'stats': self.stats,
            'mac_table': self.mac_to_port
        }
        self.state_history.append(state)
        if len(self.state_history) > 100:
            self.state_history = self.state_history[-100:]
        self.logger.info("Current state: %s", json.dumps(state, indent=2, default=str))

    def get_state_summary(self):
        return {
            'timestamp': time.time(),
            'blocked_ips_count': len(self.blocked_ips),
            'blocked_ips': list(self.blocked_ips),
            'switches_monitored': len(self.stats),
            'recent_events': self.state_history[-5:] if self.state_history else []
        }

    # ------------------------------
    # Flow programming helpers
    # ------------------------------
    def _add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)

    # ------------------------------
    # Switch and packet handling
    # ------------------------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        self.logger.info("Switch connected: %s", dpid_to_str(datapath.id))
        self.datapaths[datapath.id] = datapath

        # table-miss rule
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, 0, match, actions)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        ip_pkt = pkt.get_protocol(ipv4.ipv4)

        if not eth:
            return

        # immediate drop if blocked
        if ip_pkt and ip_pkt.src in self.blocked_ips:
            self.logger.info("Dropping packet from blocked IP: %s", ip_pkt.src)
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        if ip_pkt:
            self.ip_to_mac[ip_pkt.src] = src

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            if ip_pkt:
                match = parser.OFPMatch(
                    in_port=in_port,
                    eth_dst=dst,
                    eth_type=0x0800,
                    ipv4_src=ip_pkt.src,
                    ipv4_dst=ip_pkt.dst
                )
            else:
                match = parser.OFPMatch(in_port=in_port, eth_dst=dst)

            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self._add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self._add_flow(datapath, 1, match, actions)

        data = None if msg.buffer_id != ofproto.OFP_NO_BUFFER else msg.data
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

