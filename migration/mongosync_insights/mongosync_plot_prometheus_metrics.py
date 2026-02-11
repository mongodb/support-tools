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
        
        # Sort each percentile's results by timestamp to ensure correct chronological order
        # (multiple label keys may have interleaved timestamps)
        for pct in percentiles:
            times_list, values_list = result[pct]
            if times_list:
                paired = sorted(zip(times_list, values_list), key=lambda x: x[0])
                result[pct] = ([t for t, v in paired], [v for t, v in paired])
        
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
    
    # Create subplot layout - 19 rows x 2 columns
    # Order: Collection Copy (1-4), CEA (5-11), Buffer Service (12-14), Bulk Inserter (15-16), Verifier (17-19)
    fig = make_subplots(
        rows=19, cols=2,
        subplot_titles=(
            # Row 1-4: Collection Copy
            "Docs Copied Rate (docs/sec)", "Bytes Copied Rate (bytes/sec)",
            "Collection Copy Source Read Duration (ms)", "Collection Copy Destination Write Duration (ms)",
            "Partitions Completed Rate", "Partition Bytes Read Rate (bytes/sec)",
            "Partition Size (bytes)", "Partition Copy Duration (ms)",
            # Row 5-11: CEA metrics
            "Mongosync Phase", "Lag Time (ms)",
            "Host CPU Usage (%)", "Host Memory Usage (%)",
            "Source Ping Latency (ms)", "Destination Ping Latency (ms)",
            "Events Read Rate (events/sec)", "Events Applied Rate (events/sec)",
            "CEA Destination Write Duration (ms)", "CEA Source Read Duration (ms)",
            "Transaction Duration (ms)", "Transaction Size",
            "Retry Count", "CRUD Applier Error Counts",
            # Row 12-14: Buffer Service
            "Buffer Docs Processed Rate (docs/sec)", "Buffer Bytes Processed Rate (bytes/sec)",
            "Buffer Insert Duration (ms)", "Doc Buffers in Channel",
            "Document Size (bytes)", "Buffer Insertions Rate",
            # Row 15-16: Bulk Inserter
            "Bulk Inserter Docs Rate (docs/sec)", "Bulk Inserter Bytes Rate (bytes/sec)",
            "Docs Per Batch", "Bytes Per Batch",
            # Row 17-19: Verifier
            "Verifier Docs Hashed", "Verifier Estimated Doc Count",
            "Verifier Batch Total Time (ms)", "Verifier Payloads Processed",
            "Initial Hasher Docs Rate (docs/sec)", "Stream Hasher Buffer Size"
        ),
        specs=[
            [{}, {}],  # Row 1: Collection Copy Progress
            [{}, {}],  # Row 2: Collection Copy Durations
            [{}, {}],  # Row 3: Partition Progress
            [{}, {}],  # Row 4: Partition Histograms
            [{}, {}],  # Row 5: Phase, Lag Time
            [{}, {}],  # Row 6: CPU, Memory
            [{}, {}],  # Row 7: Ping latencies
            [{}, {}],  # Row 8: Events throughput
            [{}, {}],  # Row 9: CEA durations
            [{}, {}],  # Row 10: Transaction metrics
            [{}, {}],  # Row 11: Retry count, Errors
            [{}, {}],  # Row 12: Buffer Service throughput
            [{}, {}],  # Row 13: Buffer Service insert
            [{}, {}],  # Row 14: Buffer Service doc size
            [{}, {}],  # Row 15: Bulk Inserter throughput
            [{}, {}],  # Row 16: Bulk Inserter batch size
            [{}, {}],  # Row 17: Verifier auditor
            [{}, {}],  # Row 18: Verifier batch writer
            [{}, {}],  # Row 19: Verifier hasher
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
    
    # Helper to add histogram percentile traces
    def add_histogram_percentiles(row, col, base_metric_name, legend_group, no_data_label):
        pcts = collector.get_histogram_percentiles(base_metric_name, [50, 95, 99])
        has_data = any(len(times) > 0 for times, values in pcts.values())
        if has_data:
            for pct, (times, values) in pcts.items():
                if times:
                    fig.add_trace(
                        go.Scattergl(x=times, y=values, mode='lines', name=f'p{int(pct)}',
                                    legendgroup=legend_group),
                        row=row, col=col
                    )
        else:
            add_no_data(row, col, no_data_label)
    
    # ==================== ROWS 1-4: COLLECTION COPY ====================
    
    # Row 1, Col 1: Docs Copied Rate
    docs_copied_times, docs_copied_values = collector.get_counter_rate('mongosync_collection_copy_copied_docs_count')
    if docs_copied_times:
        fig.add_trace(
            go.Scattergl(x=docs_copied_times, y=docs_copied_values, mode='lines', name='Docs/sec',
                        legendgroup="groupDocsCopied"),
            row=1, col=1
        )
    else:
        add_no_data(1, 1, 'Docs Copied Rate')
    
    # Row 1, Col 2: Bytes Copied Rate
    bytes_copied_times, bytes_copied_values = collector.get_counter_rate('mongosync_collection_copy_copied_bytes_count')
    if bytes_copied_times:
        fig.add_trace(
            go.Scattergl(x=bytes_copied_times, y=bytes_copied_values, mode='lines', name='Bytes/sec',
                        legendgroup="groupBytesCopied"),
            row=1, col=2
        )
    else:
        add_no_data(1, 2, 'Bytes Copied Rate')
    
    # Row 2, Col 1: Collection Copy Source Read Duration
    add_histogram_percentiles(2, 1, 'mongosync_collection_copy_source_read_op_duration', 
                             'groupCCSourceRead', 'CC Source Read Duration')
    
    # Row 2, Col 2: Collection Copy Destination Write Duration
    add_histogram_percentiles(2, 2, 'mongosync_collection_copy_destination_write_op_duration',
                             'groupCCDestWrite', 'CC Dest Write Duration')
    
    # Row 3, Col 1: Partitions Completed Rate
    partitions_times, partitions_values = collector.get_counter_rate('mongosync_collection_copy_partitions_completed_count')
    if partitions_times:
        fig.add_trace(
            go.Scattergl(x=partitions_times, y=partitions_values, mode='lines', name='Partitions/sec',
                        legendgroup="groupPartitionsCompleted"),
            row=3, col=1
        )
    else:
        add_no_data(3, 1, 'Partitions Completed Rate')
    
    # Row 3, Col 2: Partition Bytes Read Rate (gauge)
    partition_bytes_times, partition_bytes_values = collector.get_gauge_series('mongosync_collection_copy_partition_copy_bytes_read_per_second')
    if partition_bytes_times:
        fig.add_trace(
            go.Scattergl(x=partition_bytes_times, y=partition_bytes_values, mode='lines', name='Bytes/sec',
                        legendgroup="groupPartitionBytesRead"),
            row=3, col=2
        )
    else:
        add_no_data(3, 2, 'Partition Bytes Read Rate')
    
    # Row 4, Col 1: Partition Size
    add_histogram_percentiles(4, 1, 'mongosync_collection_copy_partition_size',
                             'groupPartitionSize', 'Partition Size')
    
    # Row 4, Col 2: Partition Copy Duration
    add_histogram_percentiles(4, 2, 'mongosync_collection_copy_copy_partition_duration',
                             'groupPartitionDuration', 'Partition Copy Duration')
    
    # ==================== ROWS 5-11: CEA METRICS ====================
    
    # Row 5, Col 1: Phase
    phase_times, phase_values = collector.get_gauge_series('mongosync_phase')
    if phase_times:
        fig.add_trace(
            go.Scattergl(x=phase_times, y=phase_values, mode='lines', name='Phase',
                        legendgroup="groupPhase"),
            row=5, col=1
        )
    else:
        add_no_data(5, 1, 'Phase')
    
    # Row 5, Col 2: Lag Time
    lag_times, lag_values = collector.get_gauge_series('mongosync_lag_time')
    if lag_times:
        fig.add_trace(
            go.Scattergl(x=lag_times, y=lag_values, mode='lines', name='Lag Time (ms)',
                        legendgroup="groupLag"),
            row=5, col=2
        )
    else:
        add_no_data(5, 2, 'Lag Time')
    
    # Row 6, Col 1: CPU Usage
    cpu_times, cpu_values = collector.get_gauge_series('mongosync_host_cpu_usage')
    if cpu_times:
        fig.add_trace(
            go.Scattergl(x=cpu_times, y=cpu_values, mode='lines', name='CPU %',
                        legendgroup="groupCPU"),
            row=6, col=1
        )
    else:
        add_no_data(6, 1, 'CPU Usage')
    
    # Row 6, Col 2: Memory Usage
    mem_times, mem_values = collector.get_gauge_series('mongosync_host_memory_percent_used')
    if mem_times:
        fig.add_trace(
            go.Scattergl(x=mem_times, y=mem_values, mode='lines', name='Memory %',
                        legendgroup="groupMemory"),
            row=6, col=2
        )
    else:
        add_no_data(6, 2, 'Memory Usage')
    
    # Row 7, Col 1: Source Ping Latency
    add_histogram_percentiles(7, 1, 'mongosync_src_ping_latency',
                             'groupSrcPing', 'Source Ping Latency')
    
    # Row 7, Col 2: Destination Ping Latency
    add_histogram_percentiles(7, 2, 'mongosync_dst_ping_latency',
                             'groupDstPing', 'Destination Ping Latency')
    
    # Row 8, Col 1: Events Read Rate
    read_rate_times, read_rate_values = collector.get_counter_rate('mongosync_cea_change_stream_reader_events_read')
    if read_rate_times:
        fig.add_trace(
            go.Scattergl(x=read_rate_times, y=read_rate_values, mode='lines', name='Events Read/sec',
                        legendgroup="groupEventsRead"),
            row=8, col=1
        )
    else:
        add_no_data(8, 1, 'Events Read Rate')
    
    # Row 8, Col 2: Events Applied Rate
    applied_rate_times, applied_rate_values = collector.get_counter_rate('mongosync_cea_total_events_applied')
    if applied_rate_times:
        fig.add_trace(
            go.Scattergl(x=applied_rate_times, y=applied_rate_values, mode='lines', name='Events Applied/sec',
                        legendgroup="groupEventsApplied"),
            row=8, col=2
        )
    else:
        add_no_data(8, 2, 'Events Applied Rate')
    
    # Row 9, Col 1: CEA Destination Write Duration
    add_histogram_percentiles(9, 1, 'mongosync_cea_destination_write_op_duration',
                             'groupCEADstWrite', 'CEA Destination Write Duration')
    
    # Row 9, Col 2: CEA Source Read Duration
    add_histogram_percentiles(9, 2, 'mongosync_cea_source_read_op_duration',
                             'groupCEASrcRead', 'CEA Source Read Duration')
    
    # Row 10, Col 1: Transaction Duration
    add_histogram_percentiles(10, 1, 'mongosync_cea_crud_applier_txn_duration',
                             'groupTxnDuration', 'Transaction Duration')
    
    # Row 10, Col 2: Transaction Size
    add_histogram_percentiles(10, 2, 'mongosync_cea_crud_applier_txn_size',
                             'groupTxnSize', 'Transaction Size')
    
    # Row 11, Col 1: Retry Count
    retry_times, retry_values = collector.get_gauge_series('mongosync_retry_count')
    if retry_times:
        fig.add_trace(
            go.Scattergl(x=retry_times, y=retry_values, mode='lines', name='Retries',
                        legendgroup="groupRetry"),
            row=11, col=1
        )
    else:
        add_no_data(11, 1, 'Retry Count')
    
    # Row 11, Col 2: Error Counts
    error_times, error_values = collector.get_counter_rate('mongosync_cea_crud_applier_apply_event_duration_count')
    if error_times:
        fig.add_trace(
            go.Scattergl(x=error_times, y=error_values, mode='lines', name='Errors/sec',
                        legendgroup="groupErrors"),
            row=11, col=2
        )
    else:
        add_no_data(11, 2, 'Error Counts')
    
    # ==================== ROWS 12-14: BUFFER SERVICE ====================
    
    # Row 12, Col 1: Buffer Docs Processed Rate
    buf_docs_times, buf_docs_values = collector.get_counter_rate('mongosync_buffer_service_docs_processed_count')
    if buf_docs_times:
        fig.add_trace(
            go.Scattergl(x=buf_docs_times, y=buf_docs_values, mode='lines', name='Docs/sec',
                        legendgroup="groupBufDocs"),
            row=12, col=1
        )
    else:
        add_no_data(12, 1, 'Buffer Docs Processed Rate')
    
    # Row 12, Col 2: Buffer Bytes Processed Rate
    buf_bytes_times, buf_bytes_values = collector.get_counter_rate('mongosync_buffer_service_bytes_processed_count')
    if buf_bytes_times:
        fig.add_trace(
            go.Scattergl(x=buf_bytes_times, y=buf_bytes_values, mode='lines', name='Bytes/sec',
                        legendgroup="groupBufBytes"),
            row=12, col=2
        )
    else:
        add_no_data(12, 2, 'Buffer Bytes Processed Rate')
    
    # Row 13, Col 1: Buffer Insert Duration
    add_histogram_percentiles(13, 1, 'mongosync_buffer_service_insert_duration',
                             'groupBufInsertDur', 'Buffer Insert Duration')
    
    # Row 13, Col 2: Doc Buffers in Channel
    buf_channel_times, buf_channel_values = collector.get_gauge_series('mongosync_buffer_service_doc_buffers_in_channel_count')
    if buf_channel_times:
        fig.add_trace(
            go.Scattergl(x=buf_channel_times, y=buf_channel_values, mode='lines', name='Buffers',
                        legendgroup="groupBufChannel"),
            row=13, col=2
        )
    else:
        add_no_data(13, 2, 'Doc Buffers in Channel')
    
    # Row 14, Col 1: Document Size
    add_histogram_percentiles(14, 1, 'mongosync_buffer_service_doc_size',
                             'groupDocSize', 'Document Size')
    
    # Row 14, Col 2: Buffer Insertions Rate
    buf_insert_times, buf_insert_values = collector.get_counter_rate('mongosync_buffer_service_insertions_count')
    if buf_insert_times:
        fig.add_trace(
            go.Scattergl(x=buf_insert_times, y=buf_insert_values, mode='lines', name='Insertions/sec',
                        legendgroup="groupBufInsertions"),
            row=14, col=2
        )
    else:
        add_no_data(14, 2, 'Buffer Insertions Rate')
    
    # ==================== ROWS 15-16: BULK INSERTER ====================
    
    # Row 15, Col 1: Bulk Inserter Docs Rate
    bulk_docs_times, bulk_docs_values = collector.get_counter_rate('mongosync_bulk_inserter_docs_inserted_count')
    if bulk_docs_times:
        fig.add_trace(
            go.Scattergl(x=bulk_docs_times, y=bulk_docs_values, mode='lines', name='Docs/sec',
                        legendgroup="groupBulkDocs"),
            row=15, col=1
        )
    else:
        add_no_data(15, 1, 'Bulk Inserter Docs Rate')
    
    # Row 15, Col 2: Bulk Inserter Bytes Rate
    bulk_bytes_times, bulk_bytes_values = collector.get_counter_rate('mongosync_bulk_inserter_bytes_inserted_count')
    if bulk_bytes_times:
        fig.add_trace(
            go.Scattergl(x=bulk_bytes_times, y=bulk_bytes_values, mode='lines', name='Bytes/sec',
                        legendgroup="groupBulkBytes"),
            row=15, col=2
        )
    else:
        add_no_data(15, 2, 'Bulk Inserter Bytes Rate')
    
    # Row 16, Col 1: Docs Per Batch
    add_histogram_percentiles(16, 1, 'mongosync_bulk_inserter_docs_per_batch',
                             'groupDocsPerBatch', 'Docs Per Batch')
    
    # Row 16, Col 2: Bytes Per Batch
    add_histogram_percentiles(16, 2, 'mongosync_bulk_inserter_bytes_per_batch',
                             'groupBytesPerBatch', 'Bytes Per Batch')
    
    # ==================== ROWS 17-19: VERIFIER ====================
    
    # Row 17, Col 1: Verifier Docs Hashed (source and destination)
    docs_hashed_times, docs_hashed_values = collector.get_gauge_series('verifier_auditor_num_docs_hashed')
    if docs_hashed_times:
        fig.add_trace(
            go.Scattergl(x=docs_hashed_times, y=docs_hashed_values, mode='lines', name='Docs Hashed',
                        legendgroup="groupDocsHashed"),
            row=17, col=1
        )
    else:
        add_no_data(17, 1, 'Verifier Docs Hashed')
    
    # Row 17, Col 2: Verifier Estimated Doc Count
    est_docs_times, est_docs_values = collector.get_gauge_series('verifier_auditor_estimated_docs_count')
    if est_docs_times:
        fig.add_trace(
            go.Scattergl(x=est_docs_times, y=est_docs_values, mode='lines', name='Estimated Docs',
                        legendgroup="groupEstDocs"),
            row=17, col=2
        )
    else:
        add_no_data(17, 2, 'Verifier Estimated Doc Count')
    
    # Row 18, Col 1: Verifier Batch Total Time
    add_histogram_percentiles(18, 1, 'verifier_batch_writer_handle_batch_total_time',
                             'groupVerifierBatchTime', 'Verifier Batch Total Time')
    
    # Row 18, Col 2: Verifier Payloads Processed
    add_histogram_percentiles(18, 2, 'verifier_batch_writer_handle_batch_payloads_processed_total',
                             'groupVerifierPayloads', 'Verifier Payloads Processed')
    
    # Row 19, Col 1: Initial Hasher Docs Rate
    hasher_times, hasher_values = collector.get_counter_rate('verifier_initial_hasher_docs_hashed_total')
    if hasher_times:
        fig.add_trace(
            go.Scattergl(x=hasher_times, y=hasher_values, mode='lines', name='Docs/sec',
                        legendgroup="groupHasherDocs"),
            row=19, col=1
        )
    else:
        add_no_data(19, 1, 'Initial Hasher Docs Rate')
    
    # Row 19, Col 2: Stream Hasher Buffer Size
    stream_buf_times, stream_buf_values = collector.get_gauge_series('verifier_stream_hasher_buffer_size')
    if stream_buf_times:
        fig.add_trace(
            go.Scattergl(x=stream_buf_times, y=stream_buf_values, mode='lines', name='Buffer Size',
                        legendgroup="groupStreamBuf"),
            row=19, col=2
        )
    else:
        add_no_data(19, 2, 'Stream Hasher Buffer Size')
    
    # Update layout
    fig.update_layout(
        height=4275,
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
        for row in range(1, 20):
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
