import socket
import sys
import time
import os
from rudp import RUDPConnection, TYPE_SYN, TYPE_FIN

def connect_udp(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setblocking(0)
    try: s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
    except: pass
    
    conn = RUDPConnection(s, (host, port))
    print(f"Connecting to {host}:{port}...")
    
    for _ in range(3):
        conn.send_packet(0, TYPE_SYN)
        if conn._wait_ack(0) != -1:
            print("Connected!")
            return conn
        time.sleep(0.5)
    return None

def do_download(conn, filename):
    conn.flush()
    print(f"Requesting {filename}...")
    conn.send_reliable_data(f"DOWNLOAD {filename}\n".encode())
    
    resp = conn.recv_reliable_data(timeout=5.0)
    if not resp:
        print("No response from server.")
        return
        
    msg = resp.decode().strip()
    if not msg.startswith('OK'):
        print(f"Server response: {msg}")
        return
        
    try:
        filesize = int(msg.split()[1])
    except:
        print("Invalid size format.")
        return

    print(f"Size: {filesize} bytes. Downloading...")
    
    conn.send_reliable_data(b"READY\n")
    time.sleep(0.1) 
    
    start = time.time()
    conn.recv_stream_to_file(filename, filesize)
    duration = time.time() - start
    
    if os.path.exists(filename):
        actual = os.path.getsize(filename)
        mbps = (actual * 8) / (duration * 1024 * 1024) if duration > 0 else 0
        print(f"Done. {actual}/{filesize} bytes. Speed: {mbps:.2f} Mbps")
    else:
        print("Download failed.")

def main_loop(host, port):
    conn = connect_udp(host, port)
    if not conn:
        print("Could not connect.")
        return False

    try:
        while True:
            cmd = input("UDP> ").strip()
            if not cmd: continue
            
            if cmd.lower() in ('exit', 'quit'):
                break
                
            if cmd.lower().startswith('download'):
                parts = cmd.split()
                if len(parts) > 1: do_download(conn, parts[1])
                else: print("Usage: download <filename>")
            else:
                conn.send_reliable_data((cmd + "\n").encode())
                resp = conn.recv_reliable_data(timeout=2.0)
                if resp: print(resp.decode().strip())
                else: print("No response.")
                
    except (ConnectionResetError, socket.timeout):
        print("\nConnection lost.")
        return False 
    except KeyboardInterrupt:
        return True # Exit requested
    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        # Всегда пытаемся попрощаться с сервером
        try: 
            conn.send_packet(0, TYPE_FIN)
            time.sleep(0.05)
            conn.sock.close()
        except: pass

    return True # Normal exit

def start_client():
    default_ip = "127.0.0.1"
    default_port = 9090
    
    host_in = input(f"Enter Server IP (default {default_ip}): ").strip()
    HOST = host_in if host_in else default_ip
    
    port_in = input(f"Enter Port (default {default_port}): ").strip()
    PORT = int(port_in) if port_in else default_port

    while True:
        exit_requested = main_loop(HOST, PORT)
        if exit_requested is True: # Пользователь вышел сам
            sys.exit(0)
            
        ans = input("Retry connection? (y/n): ").strip().lower()
        if ans != 'y':
            sys.exit(0)

if __name__ == '__main__':
    start_client()