"""Open the assignment topology and clean up its network on exit."""
import fcntl
import os
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
import miniedit as editor

if os.geteuid() != 0:
    sys.exit('Run from the project directory: sudo python3 scripts/open_topology.py')
(ROOT / 'results').mkdir(exist_ok=True)
lock = open(ROOT / 'results/topology.lock', 'w')
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit('The assignment topology is already open. Use the existing window.')


class AssignmentEditor(editor.MiniEdit):
    def start(self):
        # Returning from the Mininet CLI with "exit" also stops the network.
        try:
            super().start()
        finally:
            self.stop()


def interrupted(signum, frame):
    raise SystemExit(0)


signal.signal(signal.SIGTERM, interrupted)
app = AssignmentEditor()
original = editor.tkFileDialog.askopenfile
try:
    editor.tkFileDialog.askopenfile = lambda **kwargs: open(ROOT / 'topology/assignment_mesh.mn', 'rb')
    app.loadTopology()
finally:
    editor.tkFileDialog.askopenfile = original
app.top.title('CEG5101 Assignment | shumin & shuhui')
try:
    app.mainloop()
except KeyboardInterrupt:
    print('\nClosing topology.')
finally:
    # Avoid Tk widget access here: the user may already have closed the window.
    if app.net is not None:
        app.net.stop()
        app.net = None
    lock.close()
