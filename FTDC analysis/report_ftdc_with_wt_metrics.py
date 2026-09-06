#!/usr/bin/env python3
"""
Decode raw MongoDB FTDC metrics.* files directly in Python (no bsondump)
and print the same summary tables as the enhanced report_1.py.

Supports:
  - a single raw metrics.* FTDC archive file
  - a diagnostic.data directory (processes metrics.* files in sorted order,
    skipping metrics.interim)
  - an already-decoded JSON file (for parity testing / fallback)
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

COUNTERS = ['insert', 'query', 'update', 'delete', 'getmore', 'command']
LATENCY_CATS = ['reads', 'writes', 'commands', 'transactions']
CPU_PATH_ALIASES = {
    'user_ms': [
        'systemMetrics.cpu.user_ms',
        'serverStatus.systemMetrics.cpu.user_ms',
        'systemMetrics.cpu.userMillis',
        'serverStatus.systemMetrics.cpu.userMillis',
    ],
    'system_ms': [
        'systemMetrics.cpu.system_ms',
        'serverStatus.systemMetrics.cpu.system_ms',
        'systemMetrics.cpu.sys_ms',
        'serverStatus.systemMetrics.cpu.sys_ms',
        'systemMetrics.cpu.systemMillis',
        'serverStatus.systemMetrics.cpu.systemMillis',
    ],
    'iowait_ms': [
        'systemMetrics.cpu.iowait_ms',
        'serverStatus.systemMetrics.cpu.iowait_ms',
        'systemMetrics.cpu.wait_ms',
        'serverStatus.systemMetrics.cpu.wait_ms',
        'systemMetrics.cpu.io_wait_ms',
        'serverStatus.systemMetrics.cpu.io_wait_ms',
        'systemMetrics.cpu.iowaitMillis',
        'serverStatus.systemMetrics.cpu.iowaitMillis',
    ],
    'context_switches': [
        'systemMetrics.cpu.ctxt',
        'serverStatus.systemMetrics.cpu.ctxt',
        'systemMetrics.cpu.context_switches',
        'serverStatus.systemMetrics.cpu.context_switches',
        'systemMetrics.cpu.contextSwitches',
        'serverStatus.systemMetrics.cpu.contextSwitches',
    ],
    'cores': [
        'systemMetrics.cpu.num_cpus',
        'serverStatus.systemMetrics.cpu.num_cpus',
        'systemMetrics.cpu.logical_cores',
        'serverStatus.systemMetrics.cpu.logical_cores',
        'systemMetrics.cpu.num_cores',
        'serverStatus.systemMetrics.cpu.num_cores',
        'systemMetrics.cpu.cores',
        'serverStatus.systemMetrics.cpu.cores',
        'systemMetrics.cpu.cpu_count',
        'serverStatus.systemMetrics.cpu.cpu_count',
        'systemMetrics.cpu.cpuCount',
        'serverStatus.systemMetrics.cpu.cpuCount',
    ],
}
SYSTEM_MEMORY_SCALED_ALIASES = {
    'total_mib': [
        ('systemMetrics.memory.total_bytes', 1 / (1024 * 1024)),
        ('serverStatus.systemMetrics.memory.total_bytes', 1 / (1024 * 1024)),
        ('systemMetrics.memory.total_kb', 1 / 1024),
        ('serverStatus.systemMetrics.memory.total_kb', 1 / 1024),
        ('systemMetrics.memory.mem_total_kb', 1 / 1024),
        ('serverStatus.systemMetrics.memory.mem_total_kb', 1 / 1024),
        ('systemMetrics.memory.MemTotal_kb', 1 / 1024),
        ('serverStatus.systemMetrics.memory.MemTotal_kb', 1 / 1024),
        ('systemMetrics.memory.total_mb', 1),
        ('serverStatus.systemMetrics.memory.total_mb', 1),
    ],
    'free_mib': [
        ('systemMetrics.memory.free_bytes', 1 / (1024 * 1024)),
        ('serverStatus.systemMetrics.memory.free_bytes', 1 / (1024 * 1024)),
        ('systemMetrics.memory.free_kb', 1 / 1024),
        ('serverStatus.systemMetrics.memory.free_kb', 1 / 1024),
        ('systemMetrics.memory.mem_free_kb', 1 / 1024),
        ('serverStatus.systemMetrics.memory.mem_free_kb', 1 / 1024),
        ('systemMetrics.memory.MemFree_kb', 1 / 1024),
        ('serverStatus.systemMetrics.memory.MemFree_kb', 1 / 1024),
        ('systemMetrics.memory.free_mb', 1),
        ('serverStatus.systemMetrics.memory.free_mb', 1),
    ],
    'available_mib': [
        ('systemMetrics.memory.available_bytes', 1 / (1024 * 1024)),
        ('serverStatus.systemMetrics.memory.available_bytes', 1 / (1024 * 1024)),
        ('systemMetrics.memory.available_kb', 1 / 1024),
        ('serverStatus.systemMetrics.memory.available_kb', 1 / 1024),
        ('systemMetrics.memory.mem_available_kb', 1 / 1024),
        ('serverStatus.systemMetrics.memory.mem_available_kb', 1 / 1024),
        ('systemMetrics.memory.MemAvailable_kb', 1 / 1024),
        ('serverStatus.systemMetrics.memory.MemAvailable_kb', 1 / 1024),
        ('systemMetrics.memory.available_mb', 1),
        ('serverStatus.systemMetrics.memory.available_mb', 1),
    ],
    'cached_mib': [
        ('systemMetrics.memory.cached_bytes', 1 / (1024 * 1024)),
        ('serverStatus.systemMetrics.memory.cached_bytes', 1 / (1024 * 1024)),
        ('systemMetrics.memory.cached_kb', 1 / 1024),
        ('serverStatus.systemMetrics.memory.cached_kb', 1 / 1024),
        ('systemMetrics.memory.mem_cached_kb', 1 / 1024),
        ('serverStatus.systemMetrics.memory.mem_cached_kb', 1 / 1024),
        ('systemMetrics.memory.Cached_kb', 1 / 1024),
        ('serverStatus.systemMetrics.memory.Cached_kb', 1 / 1024),
        ('systemMetrics.memory.cached_mb', 1),
        ('serverStatus.systemMetrics.memory.cached_mb', 1),
    ],
}
SYSTEM_MEMORY_RATIO_ALIASES = {
    'utilization_pct': [
        'systemMetrics.memory.utilization_pct',
        'serverStatus.systemMetrics.memory.utilization_pct',
        'systemMetrics.memory.used_percent',
        'serverStatus.systemMetrics.memory.used_percent',
        'systemMetrics.memory.used_pct',
        'serverStatus.systemMetrics.memory.used_pct',
        'systemMetrics.memory.percent_used',
        'serverStatus.systemMetrics.memory.percent_used',
        'systemMetrics.memory.utilization',
        'serverStatus.systemMetrics.memory.utilization',
        'systemMetrics.memory.usedPercent',
        'serverStatus.systemMetrics.memory.usedPercent',
    ],
    'fragmentation_ratio': [
        'systemMetrics.memory.fragmentation_ratio',
        'serverStatus.systemMetrics.memory.fragmentation_ratio',
        'systemMetrics.memory.mem_fragmentation_ratio',
        'serverStatus.systemMetrics.memory.mem_fragmentation_ratio',
        'systemMetrics.memory.fragmentationRatio',
        'serverStatus.systemMetrics.memory.fragmentationRatio',
    ],
}

# WiredTiger fields are stored as serverStatus.wiredTiger paths. The
# transaction aliases support older FTDC layouts that stored checkpoint
# preparation metrics below wiredTiger.transaction.
WT_METRIC_ALIASES = {
    'active_handles': [
        'serverStatus.wiredTiger.data-handle.connection data handles currently active',
    ],
    'dhandles_closed': [
        'serverStatus.wiredTiger.data-handle.connection sweep dhandles closed',
    ],
    'session_dhandles_swept': [
        'serverStatus.wiredTiger.data-handle.session dhandles swept',
    ],
    'prepare_total_time_ms': [
        'serverStatus.wiredTiger.checkpoint.prepare total time (msecs)',
        'serverStatus.wiredTiger.transaction.transaction checkpoint prepare total time (msecs)',
    ],
    'prepare_recent_time_ms': [
        'serverStatus.wiredTiger.checkpoint.prepare most recent time (msecs)',
        'serverStatus.wiredTiger.transaction.transaction checkpoint prepare most recent time (msecs)',
    ],
}

TARGET_PATHS = [
    'start',
    'end',
    'serverStatus.localTime',
    *(f'serverStatus.opcounters.{k}' for k in COUNTERS),
    *(f'serverStatus.opLatencies.{cat}.ops' for cat in LATENCY_CATS),
    *(f'serverStatus.opLatencies.{cat}.latency' for cat in LATENCY_CATS),
    'serverStatus.mem.resident',
    'serverStatus.mem.virtual',
    'serverStatus.extra_info.page_faults',
    'serverStatus.wiredTiger.cache.bytes currently in the cache',
    'serverStatus.wiredTiger.cache.maximum bytes configured',
    'serverStatus.wiredTiger.cache.tracked dirty bytes in the cache',
    'serverStatus.wiredTiger.cache.bytes read into cache',
    'serverStatus.wiredTiger.cache.bytes written from cache',
    *(alias for aliases in CPU_PATH_ALIASES.values() for alias in aliases),
    *(path for aliases in SYSTEM_MEMORY_SCALED_ALIASES.values() for path, _scale in aliases),
    *(alias for aliases in SYSTEM_MEMORY_RATIO_ALIASES.values() for alias in aliases),
    *(path for aliases in WT_METRIC_ALIASES.values() for path in aliases),
]

TARGET_PREFIXES = [
    'systemMetrics.cpu.',
    'serverStatus.systemMetrics.cpu.',
    'systemMetrics.memory.',
    'serverStatus.systemMetrics.memory.',
]


@dataclass(frozen=True)
class BSONTimestamp:
    t: int
    i: int


class BSONDecodeError(Exception):
    pass


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace('+00:00', 'Z')


def fmt_duration(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds - hours * 3600 - minutes * 60
    return f"{hours}h {minutes}m {secs:.3f}s"


def fmt_bytes(b):
    if b is None:
        return 'N/A'
    b = float(b)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if abs(b) < 1024.0:
            return f'{b:.2f} {unit}'
        b /= 1024.0
    return f'{b:.2f} PiB'


def series_stats(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return {
        'start': vals[0],
        'end': vals[-1],
        'min': min(vals),
        'max': max(vals),
        'avg': sum(vals) / len(vals),
    }


def _latency_ms(v_us):
    return f'{(v_us / 1000.0):,.3f} ms' if v_us is not None else 'N/A'


def _normalize_lookup_key(s: str) -> str:
    return ''.join(ch for ch in s.lower() if ch.isalnum())


def _normalized_mapping_lookup(mapping):
    return {_normalize_lookup_key(k): v for k, v in mapping.items() if isinstance(k, str)}


def first_present(mapping, keys):
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    norm_map = _normalized_mapping_lookup(mapping)
    for key in keys:
        value = norm_map.get(_normalize_lookup_key(key))
        if value is not None:
            return value
    return None


def first_present_scaled(mapping, scaled_keys):
    for key, scale in scaled_keys:
        value = mapping.get(key)
        if value is not None:
            return value * scale
    norm_map = _normalized_mapping_lookup(mapping)
    for key, scale in scaled_keys:
        value = norm_map.get(_normalize_lookup_key(key))
        if value is not None:
            return value * scale
    return None


def delta_from_series(series):
    vals = [v for v in series if v is not None]
    return (vals[-1] - vals[0]) if len(vals) >= 2 else None


def pct_series_from_counter(counter_series, rows):
    out = []
    prev_value = prev_t = None
    for value, row in zip(counter_series, rows):
        t = row.get('serverStatus.localTime')
        if None in (value, t, prev_value, prev_t):
            out.append(None)
        else:
            dt = t - prev_t
            dv = value - prev_value
            if dt <= 0 or dv < 0:
                out.append(None)
            else:
                out.append((dv / dt) * 100.0)
        prev_value, prev_t = value, t
    return out


def normalize_pct_series(pct_series, cores_series):
    out = []
    for pct, cores in zip(pct_series, cores_series):
        if pct is None or cores in (None, 0):
            out.append(None)
        else:
            out.append(pct / cores)
    return out


# -----------------------------
# Minimal BSON decoder
# -----------------------------

def _read_cstring(buf: bytes, pos: int) -> tuple[str, int]:
    end = buf.find(b'\x00', pos)
    if end < 0:
        raise BSONDecodeError('unterminated cstring')
    return buf[pos:end].decode('utf-8', errors='replace'), end + 1


def _decode_bson_document(buf: bytes, pos: int = 0, *, as_array: bool = False):
    if pos + 4 > len(buf):
        raise BSONDecodeError('truncated bson size')
    size = struct.unpack_from('<i', buf, pos)[0]
    if size < 5 or pos + size > len(buf):
        raise BSONDecodeError('invalid bson size')

    end = pos + size - 1
    cur = pos + 4
    doc = OrderedDict()

    while cur < end:
        etype = buf[cur]
        cur += 1
        key, cur = _read_cstring(buf, cur)
        val, cur = _decode_bson_value(buf, cur, etype)
        doc[key] = val

    if buf[end] != 0:
        raise BSONDecodeError('bson document missing terminator')

    if as_array:
        arr = []
        for i in range(len(doc)):
            arr.append(doc.get(str(i)))
        return arr, pos + size
    return doc, pos + size


def _decode_bson_value(buf: bytes, pos: int, etype: int):
    if etype == 0x01:
        return struct.unpack_from('<d', buf, pos)[0], pos + 8
    if etype == 0x02:
        slen = struct.unpack_from('<i', buf, pos)[0]
        start = pos + 4
        end = start + slen - 1
        return buf[start:end].decode('utf-8', errors='replace'), start + slen
    if etype == 0x03:
        return _decode_bson_document(buf, pos, as_array=False)
    if etype == 0x04:
        return _decode_bson_document(buf, pos, as_array=True)
    if etype == 0x05:
        blen = struct.unpack_from('<i', buf, pos)[0]
        start = pos + 5
        end = start + blen
        return buf[start:end], end
    if etype == 0x07:
        return buf[pos:pos + 12].hex(), pos + 12
    if etype == 0x08:
        return buf[pos] != 0, pos + 1
    if etype == 0x09:
        return struct.unpack_from('<q', buf, pos)[0], pos + 8
    if etype == 0x0A:
        return None, pos
    if etype == 0x10:
        return struct.unpack_from('<i', buf, pos)[0], pos + 4
    if etype == 0x11:
        inc, t = struct.unpack_from('<II', buf, pos)
        return BSONTimestamp(t=t, i=inc), pos + 8
    if etype == 0x12:
        return struct.unpack_from('<q', buf, pos)[0], pos + 8
    if etype == 0x13:
        return buf[pos:pos + 16], pos + 16
    if etype == 0xFF:
        return 'MinKey', pos
    if etype == 0x7F:
        return 'MaxKey', pos
    raise BSONDecodeError(f'unsupported bson type 0x{etype:02x}')


def iter_bson_documents_from_file(path: Path) -> Iterator[dict]:
    with path.open('rb') as fh:
        data = fh.read()
    pos = 0
    total = len(data)
    while pos + 4 <= total:
        try:
            doc, new_pos = _decode_bson_document(data, pos)
        except BSONDecodeError:
            break
        yield doc
        pos = new_pos


# -----------------------------
# FTDC metric chunk decoder
# -----------------------------

def _signed_from_varint(u: int) -> int:
    if u > 0x7FFFFFFFFFFFFFFF:
        return int(u - 0x10000000000000000)
    return int(u)


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise EOFError('truncated varint in FTDC chunk')
        b = buf[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return _signed_from_varint(value), pos
        shift += 7
        if shift > 70:
            raise ValueError('varint too large')


def _flatten_metric_schema(value, prefix: str = '') -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    if isinstance(value, OrderedDict):
        for k, v in value.items():
            path = k if not prefix else f'{prefix}.{k}'
            out.extend(_flatten_metric_schema(v, path))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            path = str(i) if not prefix else f'{prefix}.{i}'
            out.extend(_flatten_metric_schema(v, path))
    elif isinstance(value, BSONTimestamp):
        out.append((prefix + '.t', int(value.t)))
        out.append((prefix + '.i', int(value.i)))
    elif isinstance(value, bool):
        out.append((prefix, 1 if value else 0))
    elif isinstance(value, int):
        out.append((prefix, int(value)))
    elif isinstance(value, float):
        out.append((prefix, 0 if math.isnan(value) else int(value)))
    else:
        pass
    return out


def iter_chunk_target_rows(raw_chunk_data: bytes, wanted_paths: set[str], wanted_prefixes: tuple[str, ...] = ()) -> Iterator[dict[str, int | None]]:
    if len(raw_chunk_data) < 5:
        return
    payload = zlib.decompress(raw_chunk_data[4:])
    ref_doc, pos = _decode_bson_document(payload, 0)
    if pos + 8 > len(payload):
        return

    metric_count, delta_count = struct.unpack_from('<II', payload, pos)
    pos += 8

    schema = _flatten_metric_schema(ref_doc)
    if len(schema) != metric_count:
        if len(schema) > metric_count:
            schema = schema[:metric_count]
        else:
            schema.extend((f'__unknown__.{i}', 0) for i in range(len(schema), metric_count))

    paths = [p for p, _ in schema]
    baselines = [v for _, v in schema]
    wanted_indices = {
        i: p for i, p in enumerate(paths)
        if p in wanted_paths or any(p.startswith(prefix) for prefix in wanted_prefixes)
    }

    yield {p: baselines[i] for i, p in wanted_indices.items()}
    if delta_count == 0:
        return

    zero_run = 0
    series: dict[int, list[int]] = {i: [] for i in wanted_indices}
    values = list(baselines)

    for metric_idx in range(metric_count):
        cur = values[metric_idx]
        track = metric_idx in wanted_indices
        for _sample_idx in range(delta_count):
            if zero_run == 0:
                delta, pos = _read_varint(payload, pos)
                if delta == 0:
                    zero_run, pos = _read_varint(payload, pos)
            else:
                delta = 0
                zero_run -= 1
            cur += delta
            if track:
                series[metric_idx].append(cur)
        values[metric_idx] = cur

    for s in range(delta_count):
        yield {wanted_indices[i]: series[i][s] for i in wanted_indices}


# -----------------------------
# Summary logic shared by raw / decoded paths
# -----------------------------

def latency_summary_rows(first_row: dict, last_row: dict):
    out = {}
    for cat in LATENCY_CATS:
        f_lat = first_row.get(f'serverStatus.opLatencies.{cat}.latency')
        f_ops = first_row.get(f'serverStatus.opLatencies.{cat}.ops')
        l_lat = last_row.get(f'serverStatus.opLatencies.{cat}.latency')
        l_ops = last_row.get(f'serverStatus.opLatencies.{cat}.ops')
        if None in (f_lat, f_ops, l_lat, l_ops):
            continue
        d_lat = l_lat - f_lat
        d_ops = l_ops - f_ops
        out[cat] = {
            'delta_ops': d_ops,
            'delta_latency_us': d_lat,
            'window_avg_us': (d_lat / d_ops) if d_ops else None,
            'lifetime_avg_us': (l_lat / l_ops) if l_ops else None,
        }
    return out


def collect_hardware_rows(rows: list[dict]):
    resident = [r.get('serverStatus.mem.resident') for r in rows]
    virtual = [r.get('serverStatus.mem.virtual') for r in rows]
    page_faults = [r.get('serverStatus.extra_info.page_faults') for r in rows]

    cache_used = [r.get('serverStatus.wiredTiger.cache.bytes currently in the cache') for r in rows]
    cache_max = [r.get('serverStatus.wiredTiger.cache.maximum bytes configured') for r in rows]
    dirty_bytes = [r.get('serverStatus.wiredTiger.cache.tracked dirty bytes in the cache') for r in rows]
    cache_read = [r.get('serverStatus.wiredTiger.cache.bytes read into cache') for r in rows]
    cache_written = [r.get('serverStatus.wiredTiger.cache.bytes written from cache') for r in rows]

    active_handles = [first_present(r, WT_METRIC_ALIASES['active_handles']) for r in rows]
    dhandles_closed = [first_present(r, WT_METRIC_ALIASES['dhandles_closed']) for r in rows]
    session_dhandles_swept = [first_present(r, WT_METRIC_ALIASES['session_dhandles_swept']) for r in rows]
    prepare_total_time_ms = [first_present(r, WT_METRIC_ALIASES['prepare_total_time_ms']) for r in rows]
    prepare_recent_time_ms = [first_present(r, WT_METRIC_ALIASES['prepare_recent_time_ms']) for r in rows]

    cache_fill_pct = [
        (100.0 * u / m) if u is not None and m else None
        for u, m in zip(cache_used, cache_max)
    ]
    dirty_pct = [
        (100.0 * d / m) if d is not None and m else None
        for d, m in zip(dirty_bytes, cache_max)
    ]

    sysmem_total_mib = [first_present_scaled(r, SYSTEM_MEMORY_SCALED_ALIASES['total_mib']) for r in rows]
    sysmem_free_mib = [first_present_scaled(r, SYSTEM_MEMORY_SCALED_ALIASES['free_mib']) for r in rows]
    sysmem_available_mib = [first_present_scaled(r, SYSTEM_MEMORY_SCALED_ALIASES['available_mib']) for r in rows]
    sysmem_cached_mib = [first_present_scaled(r, SYSTEM_MEMORY_SCALED_ALIASES['cached_mib']) for r in rows]
    sysmem_fragmentation_ratio = [first_present(r, SYSTEM_MEMORY_RATIO_ALIASES['fragmentation_ratio']) for r in rows]

    sysmem_utilization_pct_raw = [first_present(r, SYSTEM_MEMORY_RATIO_ALIASES['utilization_pct']) for r in rows]
    sysmem_utilization_pct = []
    for raw, total, available, free in zip(sysmem_utilization_pct_raw, sysmem_total_mib, sysmem_available_mib, sysmem_free_mib):
        if raw is not None:
            sysmem_utilization_pct.append(raw)
        elif total not in (None, 0) and available is not None:
            sysmem_utilization_pct.append((1.0 - (available / total)) * 100.0)
        elif total not in (None, 0) and free is not None:
            sysmem_utilization_pct.append((1.0 - (free / total)) * 100.0)
        else:
            sysmem_utilization_pct.append(None)

    cpu_user = [first_present(r, CPU_PATH_ALIASES['user_ms']) for r in rows]
    cpu_system = [first_present(r, CPU_PATH_ALIASES['system_ms']) for r in rows]
    cpu_iowait = [first_present(r, CPU_PATH_ALIASES['iowait_ms']) for r in rows]
    cpu_context_switches = [first_present(r, CPU_PATH_ALIASES['context_switches']) for r in rows]
    cpu_cores = [first_present(r, CPU_PATH_ALIASES['cores']) for r in rows]

    cpu_user_pct = pct_series_from_counter(cpu_user, rows)
    cpu_system_pct = pct_series_from_counter(cpu_system, rows)
    cpu_iowait_pct = pct_series_from_counter(cpu_iowait, rows)
    cpu_total_pct = [
        ((u if u is not None else 0.0) + (s if s is not None else 0.0))
        if (u is not None or s is not None) else None
        for u, s in zip(cpu_user_pct, cpu_system_pct)
    ]

    cpu_total_norm_pct = normalize_pct_series(cpu_total_pct, cpu_cores)
    cpu_user_norm_pct = normalize_pct_series(cpu_user_pct, cpu_cores)
    cpu_system_norm_pct = normalize_pct_series(cpu_system_pct, cpu_cores)
    cpu_iowait_norm_pct = normalize_pct_series(cpu_iowait_pct, cpu_cores)

    def latest_non_none(series):
        vals = [v for v in series if v is not None]
        return vals[-1] if vals else None

    return {
        'resident_mib': series_stats(resident),
        'virtual_mib': series_stats(virtual),
        'page_faults': series_stats(page_faults),
        'page_faults_delta': delta_from_series(page_faults),
        'system_memory_fragmentation_ratio': series_stats(sysmem_fragmentation_ratio),
        'system_memory_utilization_pct': series_stats(sysmem_utilization_pct),
        'system_memory_cached_mib': series_stats(sysmem_cached_mib),
        'system_memory_free_mib': series_stats(sysmem_free_mib),
        'system_memory_available_mib': series_stats(sysmem_available_mib),
        'cache_used_bytes': series_stats(cache_used),
        'cache_max_bytes': latest_non_none(cache_max),
        'cache_fill_pct': series_stats(cache_fill_pct),
        'dirty_bytes': series_stats(dirty_bytes),
        'dirty_pct': series_stats(dirty_pct),
        'cache_read_delta': delta_from_series(cache_read),
        'cache_written_delta': delta_from_series(cache_written),
        'cpu_total_norm_pct': series_stats(cpu_total_norm_pct),
        'cpu_user_norm_pct': series_stats(cpu_user_norm_pct),
        'cpu_system_norm_pct': series_stats(cpu_system_norm_pct),
        'cpu_iowait_norm_pct': series_stats(cpu_iowait_norm_pct),
        'cpu_cores': series_stats(cpu_cores),
        'context_switches': series_stats(cpu_context_switches),
        'context_switches_delta': delta_from_series(cpu_context_switches),
        'wt_active_handles': series_stats(active_handles),
        'wt_dhandles_closed': series_stats(dhandles_closed),
        'wt_dhandles_closed_delta': delta_from_series(dhandles_closed),
        'wt_session_dhandles_swept': series_stats(session_dhandles_swept),
        'wt_session_dhandles_swept_delta': delta_from_series(session_dhandles_swept),
        'wt_prepare_total_time_ms': series_stats(prepare_total_time_ms),
        'wt_prepare_total_time_ms_delta': delta_from_series(prepare_total_time_ms),
        'wt_prepare_recent_time_ms': series_stats(prepare_recent_time_ms),
        'cpu_available': any(
            value is not None for value in [
                series_stats(cpu_total_norm_pct),
                series_stats(cpu_user_norm_pct),
                series_stats(cpu_system_norm_pct),
                series_stats(cpu_iowait_norm_pct),
                series_stats(cpu_cores),
                delta_from_series(cpu_context_switches),
            ]
        ),
    }


def make_summary_from_rows(rows: list[dict]) -> dict:
    if not rows:
        raise RuntimeError('No complete FTDC samples could be decoded')

    first = rows[0]
    last = rows[-1]

    first_local_ms = first['serverStatus.localTime']
    last_local_ms = last['serverStatus.localTime']
    elapsed_s = (last_local_ms - first_local_ms) / 1000

    first_ops = {k: first.get(f'serverStatus.opcounters.{k}') for k in COUNTERS}
    last_ops = {k: last.get(f'serverStatus.opcounters.{k}') for k in COUNTERS}
    delta_ops = {k: (last_ops[k] - first_ops[k]) for k in COUNTERS}

    intervals = []
    prev = None
    for r in rows:
        cur = r.get('serverStatus.localTime')
        if prev is not None and cur is not None:
            intervals.append(cur - prev)
        prev = cur

    return {
        'snapshots': len(rows),
        'start_timestamp': ms_to_iso(first_local_ms),
        'end_timestamp': ms_to_iso(last_local_ms),
        'elapsed_seconds': elapsed_s,
        'avg_interval_seconds': (sum(intervals) / len(intervals) / 1000) if intervals else 0,
        'start_opcounters': first_ops,
        'end_opcounters': last_ops,
        'delta_opcounters': delta_ops,
        'start_total_ops': sum(first_ops.values()),
        'end_total_ops': sum(last_ops.values()),
        'delta_total_ops': sum(delta_ops.values()),
        'first_top_start': ms_to_iso(first['start']),
        'first_top_end': ms_to_iso(first['end']),
        'last_top_start': ms_to_iso(last['start']),
        'last_top_end': ms_to_iso(last['end']),
        'latency': latency_summary_rows(first, last),
        'hardware': collect_hardware_rows(rows),
    }


def print_report(summary):
    print('# JSON Metrics Timeframe Report\n')

    print('## Summary\n')
    print('| Metric | Value |')
    print('| --- | --- |')
    print(f"| Complete snapshots parsed | {summary['snapshots']} |")
    print(f"| Start timestamp | {summary['start_timestamp']} |")
    print(f"| End timestamp | {summary['end_timestamp']} |")
    print(f"| Elapsed time | {fmt_duration(summary['elapsed_seconds'])} |")
    print(f"| Average sample interval | {summary['avg_interval_seconds']:.3f}s |")

    print('\n## Operation counts at start and end\n')
    print('| Counter | Start | End | Delta |')
    print('| --- | ---: | ---: | ---: |')
    for k in COUNTERS:
        print(f"| {k} | {summary['start_opcounters'][k]} | {summary['end_opcounters'][k]} | {summary['delta_opcounters'][k]} |")
    print(f"| total | {summary['start_total_ops']} | {summary['end_total_ops']} | {summary['delta_total_ops']} |")

    print('\n## Operation latencies\n')
    lat = summary['latency']
    if not lat:
        print('_No opLatencies data available in these snapshots._')
    else:
        elapsed = summary['elapsed_seconds'] or 0
        print('Average latency per operation is derived from the cumulative `opLatencies` counters. '
              'MongoDB stores those counters in microseconds, but the report displays them in milliseconds. '
              'The window average reflects only operations that occurred during the captured timeframe.\n')
        print('| Category | Ops in window | Throughput (ops/s) | Avg latency in window (ms) | Lifetime avg latency (ms) |')
        print('| --- | ---: | ---: | ---: | ---: |')
        for cat in LATENCY_CATS:
            if cat not in lat:
                continue
            d = lat[cat]
            tput = (d['delta_ops'] / elapsed) if elapsed else 0
            print(f"| {cat} | {d['delta_ops']:,} | {tput:,.1f} | {_latency_ms(d['window_avg_us'])} | {_latency_ms(d['lifetime_avg_us'])} |")

    hw = summary['hardware']
    print('\n## Hardware & resource metrics\n')

    print('### Memory\n')
    print('| Metric | Start | End | Min | Max | Avg |')
    print('| --- | ---: | ---: | ---: | ---: | ---: |')
    rs = hw['resident_mib']
    if rs:
        print(f"| Resident memory (MiB) | {rs['start']} | {rs['end']} | {rs['min']} | {rs['max']} | {rs['avg']:.1f} |")
    vs = hw['virtual_mib']
    if vs:
        print(f"| Virtual memory (MiB) | {vs['start']} | {vs['end']} | {vs['min']} | {vs['max']} | {vs['avg']:.1f} |")
    pf = hw['page_faults']
    if pf:
        print(f"| Page faults (cumulative) | {pf['start']} | {pf['end']} | {pf['min']} | {pf['max']} | {pf['avg']:.1f} |")
    if hw['page_faults_delta'] is not None:
        print(f"| Page faults during window | {hw['page_faults_delta']:,} | | | | |")
    for label, key, fmt in [
        ('System memory fragmentation ratio', 'system_memory_fragmentation_ratio', '{start:.3f} | {end:.3f} | {min:.3f} | {max:.3f} | {avg:.3f}'),
        ('System memory utilization (%)', 'system_memory_utilization_pct', '{start:.2f} | {end:.2f} | {min:.2f} | {max:.2f} | {avg:.2f}'),
        ('System memory cached (MiB)', 'system_memory_cached_mib', '{start:.1f} | {end:.1f} | {min:.1f} | {max:.1f} | {avg:.1f}'),
        ('System memory free (MiB)', 'system_memory_free_mib', '{start:.1f} | {end:.1f} | {min:.1f} | {max:.1f} | {avg:.1f}'),
        ('System memory available (MiB)', 'system_memory_available_mib', '{start:.1f} | {end:.1f} | {min:.1f} | {max:.1f} | {avg:.1f}'),
    ]:
        stats = hw[key]
        if stats:
            print('| ' + label + ' | ' + fmt.format(**stats) + ' |')

    print('\n### CPU utilization\n')
    if hw['cpu_available']:
        print('Estimated from FTDC `systemMetrics.cpu` cumulative counters. Only normalized per-core utilization is shown '
              'to keep the report focused on comparable CPU saturation across hosts.\n')
        print('| Metric | Start | End | Min | Max | Avg |')
        print('| --- | ---: | ---: | ---: | ---: | ---: |')
        for label, key in [
            ('CPU total normalized (%)', 'cpu_total_norm_pct'),
            ('CPU user normalized (%)', 'cpu_user_norm_pct'),
            ('CPU system normalized (%)', 'cpu_system_norm_pct'),
            ('CPU iowait normalized (%)', 'cpu_iowait_norm_pct'),
        ]:
            stats = hw[key]
            if stats:
                print(f"| {label} | {stats['start']:.2f} | {stats['end']:.2f} | {stats['min']:.2f} | {stats['max']:.2f} | {stats['avg']:.2f} |")
        cores = hw['cpu_cores']
        if cores:
            print(f"| CPU cores detected | {cores['start']:.0f} | {cores['end']:.0f} | {cores['min']:.0f} | {cores['max']:.0f} | {cores['avg']:.2f} |")
        ctxt = hw['context_switches']
        if ctxt:
            print(f"| Context switches (cumulative) | {ctxt['start']:,} | {ctxt['end']:,} | {ctxt['min']:,} | {ctxt['max']:,} | {ctxt['avg']:,.1f} |")
        if hw['context_switches_delta'] is not None:
            print(f"| Context switches during window | {hw['context_switches_delta']:,} | | | | |")
            elapsed = summary['elapsed_seconds'] or 0
            if elapsed > 0:
                print(f"| Avg context switches/s | {hw['context_switches_delta'] / elapsed:,.2f} | | | | |")
    else:
        print('> **Not available in this dataset.** OS-level CPU utilization is captured in the '
              'FTDC `systemMetrics` block, which is not present in this input. To include CPU, '
              'run the script against raw FTDC `metrics.*` / `diagnostic.data` that contain '
              '`systemMetrics.cpu`, not a serverStatus-only export.')

    print('\n### WiredTiger cache\n')
    print(f"Configured cache size: **{fmt_bytes(hw['cache_max_bytes'])}**\n")
    print('| Metric | Start | End | Min | Max | Avg |')
    print('| --- | ---: | ---: | ---: | ---: | ---: |')
    cu = hw['cache_used_bytes']
    if cu:
        print(f"| Bytes in cache | {fmt_bytes(cu['start'])} | {fmt_bytes(cu['end'])} | {fmt_bytes(cu['min'])} | {fmt_bytes(cu['max'])} | {fmt_bytes(cu['avg'])} |")
    cf = hw['cache_fill_pct']
    if cf:
        print(f"| Cache fill ratio (%) | {cf['start']:.2f} | {cf['end']:.2f} | {cf['min']:.2f} | {cf['max']:.2f} | {cf['avg']:.2f} |")
    db = hw['dirty_bytes']
    if db:
        print(f"| Dirty bytes | {fmt_bytes(db['start'])} | {fmt_bytes(db['end'])} | {fmt_bytes(db['min'])} | {fmt_bytes(db['max'])} | {fmt_bytes(db['avg'])} |")
    dp = hw['dirty_pct']
    if dp:
        print(f"| Dirty ratio (%) | {dp['start']:.4f} | {dp['end']:.4f} | {dp['min']:.4f} | {dp['max']:.4f} | {dp['avg']:.4f} |")
    if hw['cache_read_delta'] is not None:
        print(f"| Bytes read into cache (window) | {fmt_bytes(hw['cache_read_delta'])} | | | | |")
    if hw['cache_written_delta'] is not None:
        print(f"| Bytes written from cache (window) | {fmt_bytes(hw['cache_written_delta'])} | | | | |")

    print('\n### WiredTiger data handles\n')
    active = hw['wt_active_handles']
    if active:
        print('| Metric | Start | End | Min | Max | Avg |')
        print('| --- | ---: | ---: | ---: | ---: | ---: |')
        print(
            f"| Active data handles | "
            f"{active['start']:,.0f} | {active['end']:,.0f} | "
            f"{active['min']:,.0f} | {active['max']:,.0f} | "
            f"{active['avg']:,.1f} |"
        )
    else:
        print('_No active data handle metric available in these snapshots._')

    print('\n| Sweep metric | Start | End | Window total | Avg rate |')
    print('| --- | ---: | ---: | ---: | ---: |')
    elapsed = summary['elapsed_seconds'] or 0
    for label, stats_key, delta_key in [
        ('Connection sweep dhandles closed', 'wt_dhandles_closed', 'wt_dhandles_closed_delta'),
        ('Session dhandles swept', 'wt_session_dhandles_swept', 'wt_session_dhandles_swept_delta'),
    ]:
        stats = hw[stats_key]
        delta = hw[delta_key]
        if stats:
            rate = (delta / elapsed) if delta is not None and elapsed > 0 else None
            print(
                f"| {label} | "
                f"{stats['start']:,.0f} | {stats['end']:,.0f} | "
                f"{'N/A' if delta is None else f'{delta:,.0f}'} | "
                f"{'N/A' if rate is None else f'{rate:,.2f}/s'} |"
            )

    print('\n### WiredTiger checkpoint preparation\n')
    print('| Metric | Start | End | Min | Max | Avg | Window total | Avg rate |')
    print('| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |')

    recent = hw['wt_prepare_recent_time_ms']
    if recent:
        print(
            f"| Prepare most recent time (ms) | "
            f"{recent['start']:,.0f} | {recent['end']:,.0f} | "
            f"{recent['min']:,.0f} | {recent['max']:,.0f} | "
            f"{recent['avg']:,.1f} | N/A | N/A |"
        )

    total = hw['wt_prepare_total_time_ms']
    total_delta = hw['wt_prepare_total_time_ms_delta']
    if total:
        rate = total_delta / elapsed if total_delta is not None and elapsed > 0 else None
        print(
            f"| Prepare total time (ms, cumulative) | "
            f"{total['start']:,.0f} | {total['end']:,.0f} | "
            f"{total['min']:,.0f} | {total['max']:,.0f} | "
            f"{total['avg']:,.1f} | "
            f"{'N/A' if total_delta is None else f'{total_delta:,.0f}'} | "
            f"{'N/A' if rate is None else f'{rate:,.2f} ms/s'} |"
        )

    print('\n## Snapshot envelope details\n')
    print('| Boundary | Top-level start | serverStatus.localTime | Top-level end |')
    print('| --- | --- | --- | --- |')
    print(f"| First complete snapshot | {summary['first_top_start']} | {summary['start_timestamp']} | {summary['first_top_end']} |")
    print(f"| Last complete snapshot | {summary['last_top_start']} | {summary['end_timestamp']} | {summary['last_top_end']} |")


# -----------------------------
# Input modes
# -----------------------------

def iter_metric_files(path: Path) -> list[Path]:
    if path.is_dir():
        files = [
            p for p in sorted(path.iterdir())
            if p.is_file() and p.name.startswith('metrics.') and p.name != 'metrics.interim'
        ]
        if not files:
            raise RuntimeError(f'No metrics.* files found under {path}')
        return files
    return [path]


def summarize_raw_ftdc(path: Path) -> dict:
    wanted = set(TARGET_PATHS)
    wanted_prefixes = tuple(TARGET_PREFIXES)
    rows: list[dict] = []
    for file in iter_metric_files(path):
        for doc in iter_bson_documents_from_file(file):
            if doc.get('type') != 1:
                continue
            raw = doc.get('data')
            if not isinstance(raw, (bytes, bytearray)):
                continue
            try:
                rows.extend(iter_chunk_target_rows(bytes(raw), wanted, wanted_prefixes))
            except Exception:
                continue
    return make_summary_from_rows(rows)


def parse_decoded_json_snapshots(path: Path) -> list[dict]:
    text = path.read_text(encoding='iso-8859-1', errors='replace')
    dec = json.JSONDecoder()
    idx = 0
    snapshots = []
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = dec.raw_decode(text, idx)
        except json.JSONDecodeError:
            break
        idx = end
        if isinstance(obj, list):
            snapshots.extend(obj)
        else:
            snapshots.append(obj)
    return snapshots


def num_ejson(v):
    if isinstance(v, dict):
        for k in ('$numberLong', '$numberInt', '$numberDouble'):
            if k in v:
                return int(float(v[k])) if k == '$numberDouble' else int(v[k])
        if '$date' in v:
            return num_ejson(v['$date'])
    return v


def dig_dotted(obj, dotted_path: str):
    cur = obj
    for key in dotted_path.split('.'):
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def summarize_decoded_json(path: Path) -> dict:
    snapshots = parse_decoded_json_snapshots(path)
    if not snapshots:
        raise RuntimeError('No complete snapshots could be parsed')

    rows = []
    for s in snapshots:
        row = {}
        for target in TARGET_PATHS:
            row[target] = num_ejson(dig_dotted(s, target))
        rows.append(row)
    return make_summary_from_rows(rows)



def main() -> int:
    parser = argparse.ArgumentParser(description='Decode raw FTDC metrics.* files directly in Python and print the enhanced report.')
    parser.add_argument('input', help='raw metrics.* file, diagnostic.data directory, or decoded JSON file')
    parser.add_argument('--decoded-json', action='store_true', help='treat input as already-decoded JSON snapshots instead of raw FTDC')
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        raise SystemExit(f'Input does not exist: {path}')

    if args.decoded_json or path.suffix.lower() == '.json':
        summary = summarize_decoded_json(path)
    else:
        summary = summarize_raw_ftdc(path)

    print_report(summary)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
