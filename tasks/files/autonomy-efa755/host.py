import os, socket, subprocess, sys, time, array, json
info_r, info_w = os.pipe()
inner = r'''
import socket, time, urllib.request
time.sleep(1.0)
try:
    print("inner GET:", urllib.request.urlopen("http://127.0.0.1:8471/v1/x", timeout=3).read())
except Exception as e: print("inner GET failed:", e)
try:
    socket.create_connection(("1.1.1.1", 443), timeout=2); print("inner direct net: CONNECTED")
except Exception as e: print("inner direct net:", e)
'''
p = subprocess.Popen(["bwrap","--unshare-all","--die-with-parent","--new-session","--ro-bind","/usr","/usr",
    "--symlink","usr/lib","/lib","--symlink","usr/lib64","/lib64","--symlink","usr/bin","/bin",
    "--proc","/proc","--dev","/dev","--info-fd",str(info_w),"/usr/bin/python3","-I","-c",inner], pass_fds=(info_w,))
os.close(info_w)
info = json.loads(os.read(info_r, 4096)); pid = info["child-pid"]
a, b = socket.socketpair()
r = subprocess.run([sys.executable, "-I", "helper.py", str(pid), "8471", str(b.fileno())], pass_fds=(b.fileno(),), capture_output=True, text=True)
print("helper rc", r.returncode, r.stderr.strip()[-300:])
msg, anc, _, _ = a.recvmsg(1, socket.CMSG_LEN(4))
fd = array.array("i", anc[0][2])[0] if anc else None
print("got listener fd", fd)
if fd is not None:
    L = socket.socket(fileno=fd); L.settimeout(5)
    try:
        conn, addr = L.accept(); req = conn.recv(4096); print("host accepted from", addr, req.split(b"\r\n")[0])
        conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok"); conn.close()
    except Exception as e: print("accept failed", e)
# host-side: can a host process reach 127.0.0.1:8471 in the host netns? (should fail: different netns)
try: socket.create_connection(("127.0.0.1", 8471), timeout=1); print("host netns reach: CONNECTED (bad)")
except Exception as e: print("host netns reach:", e)
p.wait(); print("bwrap rc", p.returncode)
