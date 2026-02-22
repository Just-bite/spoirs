import socket
import sys
import time
import os
from rudp import RUDPConnection, TYPE_SYN, TYPE_FIN

HOST = '127.0.0.1'
PORT = 9090

def connect_udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setblocking(0)
    try: s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
    except: pass
    
    conn = RUDPConnection(s, (HOST, PORT))
    print(f"Connecting to {HOST}:{PORT}...")
    
    for _ in range(5):
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
    
    # Ждем ответ сервера 5 секунд
    resp = conn.recv_reliable_data(timeout=5.0)
    if not resp:
        print("No response from server.")
        return
        
    msg = resp.decode().strip()
    if not msg.startswith('OK'):
        print(f"Server: {msg}")
        return
        
    try:
        filesize = int(msg.split()[1])
    except:
        print("Invalid server response.")
        return

    print(f"File size: {filesize} bytes.")
    
    # --- СИНХРОНИЗАЦИЯ ---
    # Шлем READY и даем серверу чуть времени на обработку
    conn.send_reliable_data(b"READY\n")
    time.sleep(0.1) 
    
    print("Downloading...")
    start = time.time()
    conn.recv_stream_to_file(filename, filesize)
    duration = time.time() - start
    
    if os.path.exists(filename):
        actual = os.path.getsize(filename)
        mbps = (actual * 8) / (duration * 1024 * 1024) if duration > 0 else 0
        print(f"Done! {actual}/{filesize} bytes. Speed: {mbps:.2f} Mbps")
    else:
        print("Error: File not created.")

def main():
    conn = connect_udp()
    if not conn: return

    while True:
        try:
            cmd = input("UDP> ").strip()
            if not cmd: continue
            
            if cmd.lower() in ('exit', 'quit'):
                conn.send_packet(0, TYPE_FIN)
                break
                
            if cmd.lower().startswith('download'):
                parts = cmd.split()
                if len(parts) > 1: do_download(conn, parts[1])
                else: print("Usage: download <file>")
            else:
                conn.send_reliable_data((cmd + "\n").encode())
                # Ждем ответ на команду 2 секунды
                resp = conn.recv_reliable_data(timeout=2.0)
                if resp: print(resp.decode().strip())
                else: print("Timeout/No response.")
                
        except KeyboardInterrupt: break
        except Exception as e:
            print(f"Error: {e}")
            break
    
    try: conn.sock.close()
    except: pass

if __name__ == '__main__':
    main()