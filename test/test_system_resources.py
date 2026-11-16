import importlib
from types import SimpleNamespace

import psutil
import pytest

from routers import system


@pytest.mark.asyncio
async def test_host_metrics_read_procfs_without_mutating_psutil_global_path(
    monkeypatch, tmp_path
):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text(
        "cpu 100 0 50 850 0 0 0 0 0 0\n"
        "cpu0 50 0 25 425 0 0 0 0 0 0\n"
        "cpu1 50 0 25 425 0 0 0 0 0 0\n",
        encoding="utf-8",
    )
    (proc / "meminfo").write_text(
        "MemTotal: 1024000 kB\n"
        "MemAvailable: 256000 kB\n",
        encoding="utf-8",
    )
    (proc / "loadavg").write_text(
        "0.10 0.20 0.30 1/100 123\n",
        encoding="utf-8",
    )
    (proc / "cpuinfo").write_text(
        "processor : 0\nphysical id : 0\ncore id : 0\n\n"
        "processor : 1\nphysical id : 0\ncore id : 1\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(system, "HOST_PROC", str(proc))
    monkeypatch.setattr(system, "HOST_DISK_PATH", str(tmp_path))
    monkeypatch.setattr(system, "_last_cpu_times", None)
    disk = SimpleNamespace(total=1000, used=600, free=400, percent=60.0)
    monkeypatch.setattr(system.psutil, "disk_usage", lambda _path: disk)

    procfs_path_before = psutil.PROCFS_PATH
    importlib.reload(system)
    assert psutil.PROCFS_PATH == procfs_path_before

    # Reload resets the module's path defaults; point the route at the fixture.
    monkeypatch.setattr(system, "HOST_PROC", str(proc))
    monkeypatch.setattr(system, "HOST_DISK_PATH", str(tmp_path))
    monkeypatch.setattr(system, "_last_cpu_times", None)
    monkeypatch.setattr(system.psutil, "disk_usage", lambda _path: disk)

    first = system._read_host_proc_metrics()
    assert first["cpu"]["count_logical"] == 2
    assert first["cpu"]["count_physical"] == 2
    assert first["cpu"]["load_avg_1m"] == 0.1
    assert first["memory"]["total"] == 1024000 * 1024
    assert first["memory"]["available"] == 256000 * 1024
    assert first["memory"]["percent"] == 75.0

    (proc / "stat").write_text(
        "cpu 150 0 100 950 0 0 0 0 0 0\n"
        "cpu0 75 0 50 475 0 0 0 0 0 0\n"
        "cpu1 75 0 50 475 0 0 0 0 0 0\n",
        encoding="utf-8",
    )
    result = await system.get_system_resources()

    assert result["cpu"]["percent"] == 50.0
    assert result["memory"]["percent"] == 75.0
    assert result["disk"]["percent"] == 60.0
    assert psutil.PROCFS_PATH == procfs_path_before
