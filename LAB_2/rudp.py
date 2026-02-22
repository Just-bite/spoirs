import socket
import struct
import select
import time

# --- НАСТРОЙКИ ПРОИЗВОДИТЕЛЬНОСТИ ---
PACKET_SIZE = 65536
HEADER_FMT = '!IB'
HEADER_SIZE = struct.calcsize(HEADER_FMT)
WINDOW_SIZE = 64        # Размер окна (количество пакетов без подтверждения)
ACK_FREQUENCY = 16       # Шлать ACK только на каждый 8-й пакет (Cumulative ACK)
MAX_RETRIES = 50        # Лимит попыток

TYPE_DATA = 0
TYPE_ACK = 1
TYPE_SYN = 2
TYPE_FIN = 3

class RUDPConnection:
    def __init__(self, sock, addr=None):
        self.sock = sock
        self.addr = addr
        self.sock.setblocking(0)
        
    def flush(self):
        try:
            while True:
                data, _ = self.sock.recvfrom(65536)
        except (BlockingIOError, OSError):
            pass

    def send_packet(self, seq, type_val, data=b''):
        try:
            header = struct.pack(HEADER_FMT, seq, type_val)
            self.sock.sendto(header + data, self.addr)
        except (BlockingIOError, OSError):
            pass

    def _wait_ack_nonblocking(self):
        """Проверяет, есть ли ACK во входящем буфере. Не блокирует."""
        try:
            data, addr = self.sock.recvfrom(65536)
            if self.addr and addr != self.addr: return -1
            if len(data) < HEADER_SIZE: return -1
            seq, type_val = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
            if type_val == TYPE_ACK: return seq
            if type_val == TYPE_FIN: return -2
        except (BlockingIOError, OSError):
            pass
        return -1

    def send_reliable_data(self, data_source):
        """Отправка команд (старый надежный метод, по 1 пакету)"""
        self.flush()
        if isinstance(data_source, bytes):
            chunks = [data_source[i:i+4096] for i in range(0, len(data_source), 4096)] # Для команд оставим 4к
            if not chunks: chunks = [b'']
        else: raise ValueError("Only bytes allowed")

        base = 0
        next_seq = 0
        retries = 0

        while base < len(chunks):
            while next_seq < base + 16 and next_seq < len(chunks): # Окно для команд меньше
                self.send_packet(next_seq, TYPE_DATA, chunks[next_seq])
                next_seq += 1
            
            # Ждем ACK с таймаутом
            start = time.time()
            ack_received = -1
            while time.time() - start < 0.5:
                ready = select.select([self.sock], [], [], 0.05)
                if ready[0]:
                    ack_received = self._wait_ack_nonblocking()
                    if ack_received >= base or ack_received == -2: break
            
            if ack_received >= base:
                base = ack_received + 1
                retries = 0
            elif ack_received == -2: raise ConnectionResetError("Closed")
            else:
                retries += 1
                if retries > 20: raise ConnectionResetError("Timeout sending command")
                next_seq = base

    def recv_reliable_data(self, timeout=None):
        """Прием команд"""
        expected_seq = 0
        received_chunks = {}
        start_wait = time.time()
        
        while True:
            if timeout is not None and (time.time() - start_wait > timeout):
                return None

            ready = select.select([self.sock], [], [], 0.1)
            if not ready[0]: continue
            
            try:
                data, addr = self.sock.recvfrom(65536)
                
                if len(data) >= HEADER_SIZE:
                    seq, type_val = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
                    if type_val == TYPE_SYN:
                        self.addr = addr
                        self.send_packet(0, TYPE_ACK)
                        return None # Сброс

                if self.addr is None: self.addr = addr
                if addr != self.addr: continue
                if len(data) < HEADER_SIZE: continue
                
                seq, type_val = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
                payload = data[HEADER_SIZE:]
                
                if type_val == TYPE_FIN: return b''

                if type_val == TYPE_DATA:
                    if timeout is not None: start_wait = time.time()
                    if seq == expected_seq:
                        received_chunks[seq] = payload
                        expected_seq += 1
                        self.send_packet(expected_seq - 1, TYPE_ACK) # Команды подтверждаем всегда
                        if payload.endswith(b'\n'):
                             return b''.join(received_chunks[i] for i in sorted(received_chunks.keys()))
                    elif seq < expected_seq:
                        self.send_packet(expected_seq - 1, TYPE_ACK)
            except OSError: pass

    def send_file_bulk(self, filename):
        """Скоростная отправка файла"""
        self.flush()
        base = 0
        next_seq = 0
        file_buffer = {}
        f = open(filename, 'rb')
        retries = 0
        
        # Предварительное чтение для скорости
        try:
            while True:
                # 1. Заполняем окно "до отказа"
                while next_seq < base + WINDOW_SIZE:
                    if next_seq not in file_buffer:
                        chunk = f.read(PACKET_SIZE)
                        if not chunk: 
                            file_buffer[next_seq] = None
                            break
                        file_buffer[next_seq] = chunk
                    if file_buffer[next_seq] is None: break
                    
                    self.send_packet(next_seq, TYPE_DATA, file_buffer[next_seq])
                    next_seq += 1
                
                # Условие выхода
                if base == next_seq and (base in file_buffer and file_buffer[base] is None):
                    break
                if base == next_seq and not file_buffer: 
                    break

                # 2. Неблокирующая проверка ACK
                # Мы не ждем ACK, мы проверяем, есть ли он. 
                # Если окно полно и ACK нет -> тогда ждем.
                
                ack = -1
                # Если окно заполнено, мы обязаны ждать ACK, иначе крутимся впустую
                if next_seq >= base + WINDOW_SIZE:
                    ready = select.select([self.sock], [], [], 0.5) # Ждем
                    if ready[0]:
                        ack = self._wait_ack_nonblocking()
                else:
                    # Если окно не полно, проверяем быстро без ожидания
                    ack = self._wait_ack_nonblocking()

                if ack >= base:
                    # Cumulative ACK: удаляем все до ack включительно
                    # Удаление из словаря может быть медленным, но на таких скоростях приемлемо
                    # Оптимизация: удаляем диапазоном
                    keys_to_del = [k for k in file_buffer.keys() if k <= ack]
                    for k in keys_to_del: del file_buffer[k]
                    
                    base = ack + 1
                    retries = 0
                else:
                    # ACK не пришел (или старый)
                    # Если окно заполнено и таймаут прошел - это потеря
                    if next_seq >= base + WINDOW_SIZE and ack == -1:
                        retries += 1
                        if retries > MAX_RETRIES:
                            print(f"\n[!] Transfer timed out. Base: {base}")
                            break
                        # Go-Back-N (Упрощенно: сбрасываем next_seq, чтобы цикл while перепослал)
                        # В реальной жизни лучше Fast Retransmit, но тут пересылаем всё окно
                        next_seq = base
        finally:
            f.close()
            # Посылаем FIN
            for _ in range(5): 
                self.send_packet(next_seq, TYPE_FIN)
                time.sleep(0.005)

    def recv_stream_to_file(self, filename, expected_size, progress_callback=None):
        self.flush()
        expected_seq = 0
        bytes_written = 0
        last_activity = time.time()
        last_ack_time = time.time()
        
        # Буфер записи: пишем на диск не по 32КБ, а по 1МБ для скорости
        write_buffer = []
        write_buffer_size = 0
        MAX_WRITE_BUFFER = 1024 * 1024 

        f = open(filename, 'wb')
        try:
            while bytes_written < expected_size:
                # Ожидание данных
                ready = select.select([self.sock], [], [], 1.0)
                if not ready[0]: 
                    if time.time() - last_activity > 10.0:
                        self.send_packet(expected_seq - 1, TYPE_ACK) # Пингуем сервер
                    if time.time() - last_activity > 30.0:
                        raise ConnectionResetError("Receive timeout")
                    continue 
                
                try:
                    data, addr = self.sock.recvfrom(65536)
                    if addr != self.addr: continue
                    
                    if len(data) < HEADER_SIZE: continue
                    seq, type_val = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
                    payload = data[HEADER_SIZE:]
                    
                    if type_val == TYPE_FIN: break
                    
                    if type_val == TYPE_DATA:
                        last_activity = time.time()
                        
                        if seq == expected_seq:
                            # Добавляем в буфер записи
                            write_buffer.append(payload)
                            write_buffer_size += len(payload)
                            expected_seq += 1
                            
                            # Сбрасываем буфер на диск если он большой
                            if write_buffer_size >= MAX_WRITE_BUFFER:
                                f.write(b''.join(write_buffer))
                                bytes_written += write_buffer_size
                                write_buffer = []
                                write_buffer_size = 0
                                if progress_callback: progress_callback(bytes_written, expected_size)

                            # LOGIC: Cumulative ACK
                            # Шлем ACK если:
                            # 1. Прошло N пакетов (ACK_FREQUENCY)
                            # 2. ИЛИ Прошло много времени (>0.02с)
                            # 3. ИЛИ Это последний кусок
                            if (expected_seq % ACK_FREQUENCY == 0) or \
                               (time.time() - last_ack_time > 0.02) or \
                               (bytes_written + write_buffer_size >= expected_size):
                                
                                self.send_packet(expected_seq - 1, TYPE_ACK)
                                last_ack_time = time.time()
                                
                        elif seq < expected_seq:
                            # Если пришел повтор, значит наш ACK потерялся. 
                            # Срочно подтверждаем текущее состояние.
                            self.send_packet(expected_seq - 1, TYPE_ACK)
                            
                except OSError: pass
            
            # Дописываем остатки
            if write_buffer:
                f.write(b''.join(write_buffer))
                bytes_written += write_buffer_size
                if progress_callback: progress_callback(bytes_written, expected_size)

            # Финальные подтверждения
            for _ in range(3): self.send_packet(expected_seq - 1, TYPE_ACK)

        finally:
            f.close()