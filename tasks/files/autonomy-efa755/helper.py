# Joins the sandbox's user and net namespaces, binds 127.0.0.1:port there, sends the fd back.
import os, socket, sys, array
pid = int(sys.argv[1]); port = int(sys.argv[2]); back = int(sys.argv[3])
import fcntl
n = os.open(f"/proc/{pid}/ns/net", os.O_RDONLY); u = fcntl.ioctl(n, 0xb701)
os.setns(u, os.CLONE_NEWUSER); os.setns(n, os.CLONE_NEWNET)
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.bind(("127.0.0.1", port)); s.listen(8)
c = socket.socket(fileno=back); c.sendmsg([b"x"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [s.fileno()]))])
