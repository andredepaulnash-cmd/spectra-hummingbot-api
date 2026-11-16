import os
import threading

import psutil

from fastapi import APIRouter

router = APIRouter(tags=["System"], prefix="/system")

# Read-only host mounts supplied by Compose/Podman. Do not assign HOST_PROC to
# psutil.PROCFS_PATH: that is a process-global setting and would redirect every
# other psutil caller (including Hummingbot's own-process monitor) into the
# host PID namespace, where container PID 1 is not the host's PID 1.
HOST_PROC = os.environ.get("HOST_PROC", "/proc")
HOST_DISK_PATH = os.environ.get("HOST_DISK_PATH", "/")

_cpu_sample_lock = threading.Lock()
_last_cpu_times: tuple[int, int] | None = None


def _read_cpu_counts(stat_lines: list[str]) -> tuple[int, int]:
    logical = sum(
        1
        for line in stat_lines
        if line.startswith("cpu")
        and line[3:].split(" ", 1)[0].isdigit()
    )
    if logical <= 0:
        logical = os.cpu_count() or 1

    physical_cores: set[tuple[str, str]] = set()
    try:
        with open(os.path.join(HOST_PROC, "cpuinfo"), encoding="utf-8") as stream:
            blocks = stream.read().strip().split("\n\n")
        for block in blocks:
            fields = {}
            for line in block.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    fields[key.strip()] = value.strip()
            physical_id = fields.get("physical id")
            core_id = fields.get("core id")
            if physical_id is not None and core_id is not None:
                physical_cores.add((physical_id, core_id))
    except OSError:
        pass

    return logical, len(physical_cores) or logical


def _read_host_proc_metrics() -> dict:
    global _last_cpu_times

    with open(os.path.join(HOST_PROC, "stat"), encoding="utf-8") as stream:
        stat_lines = stream.read().splitlines()
    cpu_line = next(line for line in stat_lines if line.startswith("cpu "))
    cpu_values = [int(value) for value in cpu_line.split()[1:]]
    if len(cpu_values) < 4:
        raise ValueError("host /proc/stat has an incomplete aggregate CPU row")

    # Linux reports guest time inside user/nice already; exclude the guest
    # columns to avoid double-counting them.
    total = sum(cpu_values[:8])
    idle = cpu_values[3] + (cpu_values[4] if len(cpu_values) > 4 else 0)
    with _cpu_sample_lock:
        previous = _last_cpu_times
        _last_cpu_times = (total, idle)
    if previous is None:
        cpu_percent = 0.0
    else:
        delta_total = total - previous[0]
        delta_idle = idle - previous[1]
        cpu_percent = (
            0.0
            if delta_total <= 0
            else max(0.0, min(100.0, 100.0 * (delta_total - delta_idle) / delta_total))
        )

    memory = {}
    with open(os.path.join(HOST_PROC, "meminfo"), encoding="utf-8") as stream:
        for line in stream:
            if ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            parts = raw_value.split()
            if not parts:
                continue
            value = int(parts[0])
            if len(parts) > 1 and parts[1].lower() == "kb":
                value *= 1024
            memory[key.strip()] = value

    total_memory = memory.get("MemTotal")
    available_memory = memory.get("MemAvailable")
    if total_memory is None:
        raise ValueError("host /proc/meminfo has no MemTotal")
    if available_memory is None:
        available_memory = (
            memory.get("MemFree", 0)
            + memory.get("Buffers", 0)
            + memory.get("Cached", 0)
            + memory.get("SReclaimable", 0)
            - memory.get("Shmem", 0)
        )
    available_memory = max(0, min(total_memory, available_memory))
    used_memory = total_memory - available_memory

    with open(os.path.join(HOST_PROC, "loadavg"), encoding="utf-8") as stream:
        load_values = stream.read().split()
    if len(load_values) < 3:
        raise ValueError("host /proc/loadavg has fewer than three load averages")
    logical_count, physical_count = _read_cpu_counts(stat_lines)

    return {
        "cpu": {
            "percent": cpu_percent,
            "count_logical": logical_count,
            "count_physical": physical_count,
            "load_avg_1m": float(load_values[0]),
            "load_avg_5m": float(load_values[1]),
            "load_avg_15m": float(load_values[2]),
        },
        "memory": {
            "total": total_memory,
            "available": available_memory,
            "used": used_memory,
            "percent": (100.0 * used_memory / total_memory) if total_memory else 0.0,
        },
    }


@router.get("/resources")
async def get_system_resources():
    """
    Get host machine CPU, RAM, load, and disk usage.

    Host CPU and memory values are read from the mounted procfs files directly.
    This avoids changing psutil's process-global procfs path, which would break
    Hummingbot's own-process monitoring inside a container.
    """
    try:
        metrics = _read_host_proc_metrics()
    except (OSError, ValueError, StopIteration):
        # The route also works when a host procfs mount is unavailable. In that
        # case, report container/local process metrics without mutating psutil.
        try:
            load_avg = psutil.getloadavg()
        except (OSError, AttributeError):
            load_avg = (0.0, 0.0, 0.0)
        vm = psutil.virtual_memory()
        metrics = {
            "cpu": {
                "percent": psutil.cpu_percent(interval=None),
                "count_logical": psutil.cpu_count(logical=True),
                "count_physical": psutil.cpu_count(logical=False),
                "load_avg_1m": load_avg[0],
                "load_avg_5m": load_avg[1],
                "load_avg_15m": load_avg[2],
            },
            "memory": {
                "total": vm.total,
                "available": vm.available,
                "used": vm.used,
                "percent": vm.percent,
            },
        }

    disk = psutil.disk_usage(HOST_DISK_PATH)
    metrics["disk"] = {
        # Display label only; the stats are for the filesystem containing
        # HOST_DISK_PATH (the host root partition).
        "mountpoint": "host root",
        "total": disk.total,
        "used": disk.used,
        "free": disk.free,
        "percent": disk.percent,
    }
    return metrics
