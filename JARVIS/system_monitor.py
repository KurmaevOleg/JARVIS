import time
import psutil

psutil.cpu_percent(interval=None)  # прогрев

def get_cpu_usage() -> float:
    return psutil.cpu_percent(interval=None)

def get_memory_usage():
    mem = psutil.virtual_memory()
    used = mem.used / (1024**3)
    total = mem.total / (1024**3)
    percent = mem.percent
    return used, total, percent

def get_disk_usage():
    disk = psutil.disk_usage('C:/')
    free = disk.free / (1024**3)
    total = disk.total / (1024**3)
    percent = disk.percent
    return free, total, percent

def get_network_io():
    p1 = psutil.net_io_counters()
    time.sleep(1)
    p2 = psutil.net_io_counters()
    sent = (p2.bytes_sent - p1.bytes_sent) / 1024
    recv = (p2.bytes_recv - p1.bytes_recv) / 1024
    return recv, sent

def get_system_report():
    cpu = get_cpu_usage()
    mem_used, mem_total, mem_percent = get_memory_usage()
    disk_free, disk_total, disk_percent = get_disk_usage()

    return (
        f"CPU {cpu:.1f}%. "
        f"ОЗУ: занято {mem_used:.1f} ГБ из {mem_total:.1f} ГБ ({mem_percent:.1f}%). "
        f"Диск: свободно {disk_free:.1f} ГБ из {disk_total:.1f} ГБ ({disk_percent:.1f}% занято)."
    )