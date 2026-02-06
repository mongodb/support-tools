"""
Prometheus metrics parsing and plotting for mongosync_metrics.log files.
Parses Prometheus exposition format metrics embedded in JSON log lines.
"""
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from plotly.subplots import make_subplots
import json
import re
import logging
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Any, Tuple, Optional

logger = logging.getLogger(__name__)

# Prometheus metric line regex pattern
# Matches: metric_name{labels} value timestamp
# or: metric_name value timestamp
METRIC_LINE_PATTERN = re.compile(
    r'^([a-zA-Z_:][a-zA-Z0-9_:]*)'  # Metric name
    r'(?:\{([^}]*)\})?'              # Optional labels in braces
    r'\s+'                           # Whitespace
    r'([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)'  # Value (including scientific notation)
    r'(?:\s+(\d+))?'                 # Optional timestamp
    r'\s*$'                          # End of line
)

# Label parsing pattern
LABEL_PATTERN = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="([^"]*)"')


def parse_labels(labels_str: str) -> Dict[str, str]:
    """Parse Prometheus label string into a dictionary."""
    if not labels_str:
        return {}
    return dict(LABEL_PATTERN.findall(labels_str))


def parse_prometheus_message(message: str) -> List[Dict[str, Any]]:
    """
    Parse a Prometheus exposition format message into a list of metric dictionaries.
    
    Args:
        message: The message field from the JSON log line containing Prometheus metrics
        
    Returns:
        List of parsed metrics, each containing:
        - name: metric name
        - labels: dict of labels
        - value: float value
        - timestamp: optional Unix timestamp
    """
    metrics = []
    
    # Split by newlines (handling \n in the JSON string)
    lines = message.replace('\\n', '\n').split('\n')
    
    for line in lines:
        line = line.strip()
        
        # Skip empty lines and comments (HELP, TYPE)
        if not line or line.startswith('#'):
            continue
        
        match = METRIC_LINE_PATTERN.match(line)
        if match:
            name, labels_str, value_str, timestamp_str = match.groups()
            
            try:
                value = float(value_str)
            except ValueError:
                continue
            
            metric = {
                'name': name,
                'labels': parse_labels(labels_str) if labels_str else {},
                'value': value,
            }
            
            if timestamp_str:
                metric['timestamp'] = int(timestamp_str)
            
            metrics.append(metric)
    
    return metrics


def parse_metrics_log_line(line: str) -> Tuple[Optional[datetime], List[Dict[str, Any]]]:
    """
    Parse a single JSON log line containing Prometheus metrics.
    
    Args:
        line: JSON string with 'time' and 'message' fields
        
    Returns:
        Tuple of (timestamp as datetime, list of parsed metrics)
    """
    try:
        json_obj = json.loads(line)
        time_str = json_obj.get('time', '')
        message = json_obj.get('message', '')
        
        # Parse timestamp
        timestamp = None
        if time_str:
            try:
                # Handle ISO format with microseconds
                timestamp = datetime.strptime(time_str[:26], "%Y-%m-%dT%H:%M:%S.%f")
            except ValueError:
                try:
                    timestamp = datetime.strptime(time_str[:19], "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    pass
        
        # Parse Prometheus metrics from message
        metrics = parse_prometheus_message(message)
        
        return timestamp, metrics
        
    except json.JSONDecodeError:
        return None, []


class MetricsCollector:
    """Collects and organizes Prometheus metrics from mongosync_metrics.log files."""
    
    def __init__(self):
        # Time series data: {metric_name: {labels_key: [(timestamp, value), ...]}}
        self.time_series = defaultdict(lambda: defaultdict(list))
        
        # Histogram data: {metric_name: {labels_key: {timestamp: {bucket_le: count}}}}
        # Indexed by timestamp first for O(1) lookup during percentile calculation
        self.histograms = defaultdict(lambda: defaultdict(dict))
        
        # Counters for tracking
        self.line_count = 0
        self.metrics_count = 0
        
    def _labels_to_key(self, labels: Dict[str, str], exclude_keys: List[str] = None) -> str:
        """Convert labels dict to a hashable key string, optionally excluding certain keys."""
        exclude_keys = exclude_keys or []
        filtered = {k: v for k, v in sorted(labels.items()) if k not in exclude_keys}
        return json.dumps(filtered, sort_keys=True)
    
    def add_metric(self, timestamp: datetime, metric: Dict[str, Any]):
        """Add a single metric data point to the collector."""
        name = metric['name']
        labels = metric['labels']
        value = metric['value']
        
        self.metrics_count += 1
        
        # Handle histogram buckets specially
        if '_bucket' in name:
            # Extract base name (remove _bucket suffix)
            base_name = name.replace('_bucket', '')
            le = labels.get('le', '+Inf')
            
            # Create key without 'le' label
            key = self._labels_to_key(labels, exclude_keys=['le'])
            
            # Store indexed by timestamp for O(1) lookup during percentile calculation
            if timestamp not in self.histograms[base_name][key]:
                self.histograms[base_name][key][timestamp] = {}
            self.histograms[base_name][key][timestamp][le] = value
        elif '_sum' in name or '_count' in name:
            # Histogram sum/count - store in time_series
            key = self._labels_to_key(labels)
            self.time_series[name][key].append((timestamp, value))
        else:
            # Regular gauge or counter
            key = self._labels_to_key(labels)
            self.time_series[name][key].append((timestamp, value))
    
    def process_line(self, line: str):
        """Process a single log line."""
        self.line_count += 1
        
        timestamp, metrics = parse_metrics_log_line(line)
        
        if timestamp and metrics:
            for metric in metrics:
                self.add_metric(timestamp, metric)
    
    def get_gauge_series(self, metric_name: str) -> Tuple[List[datetime], List[float]]:
        """Get time series data for a gauge metric."""
        if metric_name not in self.time_series:
            return [], []
        
        # Combine all label variants (usually there's just one for gauges)
        all_points = []
        for key, points in self.time_series[metric_name].items():
            all_points.extend(points)
        
        if not all_points:
            return [], []
        
        # Sort by timestamp
        all_points.sort(key=lambda x: x[0])
        
        times = [p[0] for p in all_points]
        values = [p[1] for p in all_points]
        
        return times, values
    
    def get_counter_rate(self, metric_name: str) -> Tuple[List[datetime], List[float]]:
        """Calculate rate of change for a counter metric."""
        times, values = self.get_gauge_series(metric_name)
        
        if len(times) < 2:
            return [], []
        
        rate_times = []
        rate_values = []
        
        for i in range(1, len(times)):
            dt = (times[i] - times[i-1]).total_seconds()
            if dt > 0:
                rate = (values[i] - values[i-1]) / dt
                rate_times.append(times[i])
                rate_values.append(max(0, rate))  # Rates shouldn't be negative
        
        return rate_times, rate_values
    
    def get_histogram_percentiles(self, base_name: str, percentiles: List[float] = None) -> Dict[float, Tuple[List[datetime], List[float]]]:
        """
        Calculate percentiles from histogram bucket data.
        
        Args:
            base_name: Base metric name (without _bucket suffix)
            percentiles: List of percentiles to calculate (default: [50, 95, 99])
            
        Returns:
            Dict mapping percentile to (times, values) tuple
        """
        if percentiles is None:
            percentiles = [50, 95, 99]
        
        if base_name not in self.histograms:
            return {p: ([], []) for p in percentiles}
        
        result = {p: ([], []) for p in percentiles}
        
        # Process each label variant
        for key, timestamp_data in self.histograms[base_name].items():
            # Iterate through timestamps directly (O(T log T) for sorting)
            for ts in sorted(timestamp_data.keys()):
                # O(1) lookup - get all bucket values for this timestamp
                bucket_values = timestamp_data[ts]
                
                # Build cumulative distribution for this timestamp
                buckets = []
                for le_str, count in bucket_values.items():
                    try:
                        le = float(le_str) if le_str != '+Inf' else float('inf')
                        buckets.append((le, count))
                    except ValueError:
                        pass
                
                if not buckets:
                    continue
                
                # Sort by le value
                buckets.sort(key=lambda x: x[0])
                
                # Calculate percentiles using linear interpolation
                total_count = buckets[-1][1] if buckets else 0
                
                if total_count == 0:
                    continue
                
                for pct in percentiles:
                    target_count = total_count * (pct / 100.0)
                    
                    # Find the bucket containing the percentile
                    prev_le = 0
                    prev_count = 0
                    
                    for le, count in buckets:
                        if count >= target_count:
                            # Linear interpolation within bucket
                            if count == prev_count:
                                value = le
                            else:
                                fraction = (target_count - prev_count) / (count - prev_count)
                                value = prev_le + fraction * (le - prev_le)
                            
                            if value != float('inf'):
                                result[pct][0].append(ts)
                                result[pct][1].append(value)
                            break
                        
                        prev_le = le
                        prev_count = count
        
        return result


def create_metrics_plots(collector: MetricsCollector) -> str:
    """
    Create Plotly plots for the collected Prometheus metrics.
    
    Args:
        collector: MetricsCollector instance with parsed data
        
    Returns:
        JSON string of the Plotly figure
    """
    logger.info(f"Creating metrics plots from {collector.metrics_count} metric points")
    
    # Create subplot layout - 7 rows x 2 columns
    fig = make_subplots(
        rows=7, cols=2,
        subplot_titles=(
            "Mongosync Phase", "Lag Time (ms)",
            "Host CPU Usage (%)", "Host Memory Usage (%)",
            "Source Ping Latency (ms)", "Destination Ping Latency (ms)",
            "Events Read Rate (events/sec)", "Events Applied Rate (events/sec)",
            "CEA Destination Write Duration (ms)", "CEA Source Read Duration (ms)",
            "Transaction Duration (ms)", "Transaction Size",
            "Retry Count", "CRUD Applier Error Counts"
        ),
        specs=[
            [{}, {}],  # Row 1: Phase, Lag Time
            [{}, {}],  # Row 2: CPU, Memory
            [{}, {}],  # Row 3: Ping latencies
            [{}, {}],  # Row 4: Events throughput
            [{}, {}],  # Row 5: CEA durations
            [{}, {}],  # Row 6: Transaction metrics
            [{}, {}],  # Row 7: Retry count, Errors
        ]
    )
    
    # Helper to add NO DATA placeholder
    def add_no_data(row, col, name):
        fig.add_trace(
            go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name=name,
                      textfont=dict(size=30, color="black")),
            row=row, col=col
        )
        fig.update_yaxes(range=[-1, 1], row=row, col=col)
        fig.update_xaxes(range=[-1, 1], row=row, col=col)
    
    # Row 1, Col 1: Phase
    phase_times, phase_values = collector.get_gauge_series('mongosync_phase')
    if phase_times:
        fig.add_trace(
            go.Scattergl(x=phase_times, y=phase_values, mode='lines', name='Phase',
                        legendgroup="groupPhase"),
            row=1, col=1
        )
    else:
        add_no_data(1, 1, 'Phase')
    
    # Row 1, Col 2: Lag Time
    lag_times, lag_values = collector.get_gauge_series('mongosync_lag_time')
    if lag_times:
        fig.add_trace(
            go.Scattergl(x=lag_times, y=lag_values, mode='lines', name='Lag Time (ms)',
                        legendgroup="groupLag"),
            row=1, col=2
        )
    else:
        add_no_data(1, 2, 'Lag Time')
    
    # Row 2, Col 1: CPU Usage
    cpu_times, cpu_values = collector.get_gauge_series('mongosync_host_cpu_usage')
    if cpu_times:
        fig.add_trace(
            go.Scattergl(x=cpu_times, y=cpu_values, mode='lines', name='CPU %',
                        legendgroup="groupCPU"),
            row=2, col=1
        )
    else:
        add_no_data(2, 1, 'CPU Usage')
    
    # Row 2, Col 2: Memory Usage
    mem_times, mem_values = collector.get_gauge_series('mongosync_host_memory_percent_used')
    if mem_times:
        fig.add_trace(
            go.Scattergl(x=mem_times, y=mem_values, mode='lines', name='Memory %',
                        legendgroup="groupMemory"),
            row=2, col=2
        )
    else:
        add_no_data(2, 2, 'Memory Usage')
    
    # Row 3, Col 1: Source Ping Latency (histogram percentiles)
    src_ping_pcts = collector.get_histogram_percentiles('mongosync_src_ping_latency', [50, 95, 99])
    has_src_ping = any(len(times) > 0 for times, values in src_ping_pcts.values())
    if has_src_ping:
        for pct, (times, values) in src_ping_pcts.items():
            if times:
                fig.add_trace(
                    go.Scattergl(x=times, y=values, mode='lines', name=f'p{int(pct)}',
                                legendgroup="groupSrcPing"),
                    row=3, col=1
                )
    else:
        add_no_data(3, 1, 'Source Ping Latency')
    
    # Row 3, Col 2: Destination Ping Latency (histogram percentiles)
    dst_ping_pcts = collector.get_histogram_percentiles('mongosync_dst_ping_latency', [50, 95, 99])
    has_dst_ping = any(len(times) > 0 for times, values in dst_ping_pcts.values())
    if has_dst_ping:
        for pct, (times, values) in dst_ping_pcts.items():
            if times:
                fig.add_trace(
                    go.Scattergl(x=times, y=values, mode='lines', name=f'p{int(pct)}',
                                legendgroup="groupDstPing"),
                    row=3, col=2
                )
    else:
        add_no_data(3, 2, 'Destination Ping Latency')
    
    # Row 4, Col 1: Events Read Rate
    read_rate_times, read_rate_values = collector.get_counter_rate('mongosync_cea_change_stream_reader_events_read')
    if read_rate_times:
        fig.add_trace(
            go.Scattergl(x=read_rate_times, y=read_rate_values, mode='lines', name='Events Read/sec',
                        legendgroup="groupEventsRead"),
            row=4, col=1
        )
    else:
        add_no_data(4, 1, 'Events Read Rate')
    
    # Row 4, Col 2: Events Applied Rate
    applied_rate_times, applied_rate_values = collector.get_counter_rate('mongosync_cea_total_events_applied')
    if applied_rate_times:
        fig.add_trace(
            go.Scattergl(x=applied_rate_times, y=applied_rate_values, mode='lines', name='Events Applied/sec',
                        legendgroup="groupEventsApplied"),
            row=4, col=2
        )
    else:
        add_no_data(4, 2, 'Events Applied Rate')
    
    # Row 5, Col 1: CEA Destination Write Duration (histogram percentiles)
    cea_dst_write_pcts = collector.get_histogram_percentiles('mongosync_cea_destination_write_op_duration', [50, 95, 99])
    has_cea_dst = any(len(times) > 0 for times, values in cea_dst_write_pcts.values())
    if has_cea_dst:
        for pct, (times, values) in cea_dst_write_pcts.items():
            if times:
                fig.add_trace(
                    go.Scattergl(x=times, y=values, mode='lines', name=f'p{int(pct)}',
                                legendgroup="groupCEADstWrite"),
                    row=5, col=1
                )
    else:
        add_no_data(5, 1, 'CEA Destination Write Duration')
    
    # Row 5, Col 2: CEA Source Read Duration (histogram percentiles)
    cea_src_read_pcts = collector.get_histogram_percentiles('mongosync_cea_source_read_op_duration', [50, 95, 99])
    has_cea_src = any(len(times) > 0 for times, values in cea_src_read_pcts.values())
    if has_cea_src:
        for pct, (times, values) in cea_src_read_pcts.items():
            if times:
                fig.add_trace(
                    go.Scattergl(x=times, y=values, mode='lines', name=f'p{int(pct)}',
                                legendgroup="groupCEASrcRead"),
                    row=5, col=2
                )
    else:
        add_no_data(5, 2, 'CEA Source Read Duration')
    
    # Row 6, Col 1: Transaction Duration (histogram percentiles)
    txn_duration_pcts = collector.get_histogram_percentiles('mongosync_cea_crud_applier_txn_duration', [50, 95, 99])
    has_txn_dur = any(len(times) > 0 for times, values in txn_duration_pcts.values())
    if has_txn_dur:
        for pct, (times, values) in txn_duration_pcts.items():
            if times:
                fig.add_trace(
                    go.Scattergl(x=times, y=values, mode='lines', name=f'p{int(pct)}',
                                legendgroup="groupTxnDuration"),
                    row=6, col=1
                )
    else:
        add_no_data(6, 1, 'Transaction Duration')
    
    # Row 6, Col 2: Transaction Size (histogram percentiles)
    txn_size_pcts = collector.get_histogram_percentiles('mongosync_cea_crud_applier_txn_size', [50, 95, 99])
    has_txn_size = any(len(times) > 0 for times, values in txn_size_pcts.values())
    if has_txn_size:
        for pct, (times, values) in txn_size_pcts.items():
            if times:
                fig.add_trace(
                    go.Scattergl(x=times, y=values, mode='lines', name=f'p{int(pct)}',
                                legendgroup="groupTxnSize"),
                    row=6, col=2
                )
    else:
        add_no_data(6, 2, 'Transaction Size')
    
    # Row 7, Col 1: Retry Count
    retry_times, retry_values = collector.get_gauge_series('mongosync_retry_count')
    if retry_times:
        fig.add_trace(
            go.Scattergl(x=retry_times, y=retry_values, mode='lines', name='Retries',
                        legendgroup="groupRetry"),
            row=7, col=1
        )
    else:
        add_no_data(7, 1, 'Retry Count')
    
    # Row 7, Col 2: Error Counts (from apply_event_duration with is_error=true)
    # Get the _count metric for errors
    error_times, error_values = collector.get_counter_rate('mongosync_cea_crud_applier_apply_event_duration_count')
    if error_times:
        fig.add_trace(
            go.Scattergl(x=error_times, y=error_values, mode='lines', name='Errors/sec',
                        legendgroup="groupErrors"),
            row=7, col=2
        )
    else:
        add_no_data(7, 2, 'Error Counts')
    
    # Update layout
    fig.update_layout(
        height=1575,
        width=1450,
        title_text="Mongosync Prometheus Metrics",
        legend_tracegroupgap=170,
        showlegend=False
    )
    
    # Force all y-axes to start at 0
    fig.update_yaxes(rangemode='tozero')
    
    # Get global date range for X-axis synchronization
    all_times = []
    for metric_data in collector.time_series.values():
        for points in metric_data.values():
            all_times.extend([p[0] for p in points])
    
    if all_times:
        global_min_date = min(all_times)
        global_max_date = max(all_times)
        
        # Synchronize X-axis across all plots
        for row in range(1, 8):
            for col in range(1, 3):
                fig.update_xaxes(range=[global_min_date, global_max_date], row=row, col=col)
    
    # Convert to JSON
    return json.dumps(fig, cls=PlotlyJSONEncoder)


def process_metrics_lines(lines_iterator) -> str:
    """
    Process an iterator of metrics log lines and create plots.
    
    Args:
        lines_iterator: Iterator yielding log lines (bytes or str)
        
    Returns:
        JSON string of the Plotly figure, or empty string if no data
    """
    collector = MetricsCollector()
    
    for line in lines_iterator:
        # Handle both bytes and string input
        if isinstance(line, bytes):
            line = line.decode('utf-8', errors='replace')
        line = line.strip()
        
        if not line or not line.startswith('{'):
            continue
        
        collector.process_line(line)
    
    logger.info(f"Processed {collector.line_count} metrics lines, extracted {collector.metrics_count} metric points")
    
    if collector.metrics_count == 0:
        return ""
    
    return create_metrics_plots(collector)
