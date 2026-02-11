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
    
    # Create subplot layout - 35 rows x 2 columns
    # Organized by section from mongosync_metrics.json
    fig = make_subplots(
        rows=35, cols=2,
        subplot_titles=(
            # Row 1-4: Collection Copy & Partition
            "Docs Copied Rate (docs/sec)", "Bytes Copied Rate (bytes/sec)",
            "Collection Copy Source Read Duration (ms)", "Collection Copy Destination Write Duration (ms)",
            "Partitions Completed Rate", "Partition Bytes Read Rate (bytes/sec)",
            "Partition Size (bytes)", "Partition Copy Duration (ms)",
            # Row 5: Collection Copy Cleanup
            "Partitions Deleted Rate", "Docs Deleted Rate",
            # Row 6: Collection Copy Cleanup (continued)
            "Bytes Deleted Rate", "",
            # Row 7-11: Core Replication and Phase + Host Load
            "Mongosync Phase", "Lag Time (sec)",
            "Host CPU Usage (%)", "Host Memory Usage (%)",
            "Source Ping Latency (ms)", "Destination Ping Latency (ms)",
            "Source Unavailable", "Destination Unavailable",
            "Verifier Lag Time (sec)", "Retry Count",
            # Row 12-13: CEA Reader & Overall
            "Events Read Rate (events/sec)", "Events Applied Rate (events/sec)",
            "Bytes Read Rate (bytes/sec)", "DDL Events Applied Rate",
            # Row 14-15: CEA Durations
            "CEA Destination Write Duration (ms)", "CEA Source Read Duration (ms)",
            "Transaction Duration (ms)", "Transaction Size",
            # Row 16-19: CEA CRUD Applier
            "Single Event Count Rate", "Single Write Duration (ms)",
            "Duplicate Key Errors Rate", "One-by-One Events Rate",
            "Default Errors Rate", "Refetch Duration (ms)",
            "Apply Event Duration (ms)", "Total CRUD Events Rate",
            # Row 20-21: CEA CRUD Applier (continued)
            "LWS Get Entry Duration (ms)", "LWS Set Entry Duration (ms)",
            "Reader-Dispatcher Channel Util", "Dispatcher-Processor Channel Util",
            # Row 22: CEA Spread
            "Spread Disparity", "",
            # Row 23-24: Hot Documents
            "Hot Doc States Read Duration (ms)", "Hot Doc Refetch Duration (ms)",
            "Hot Doc Apply Duration (ms)", "Hot Doc Events Skipped Rate",
            # Row 25: Indexes
            "Index Create Duration (ms)", "Indexes Created Rate",
            # Row 26-28: Buffer Service
            "Buffer Docs Processed Rate (docs/sec)", "Buffer Bytes Processed Rate (bytes/sec)",
            "Buffer Insert Duration (ms)", "Doc Buffers in Channel",
            "Document Size (bytes)", "Buffer Insertions Rate",
            # Row 29-30: Bulk Inserter
            "Bulk Inserter Docs Rate (docs/sec)", "Bulk Inserter Bytes Rate (bytes/sec)",
            "Docs Per Batch", "Bytes Per Batch",
            # Row 31-35: Verifier
            "Verifier Docs Hashed", "Verifier Estimated Doc Count",
            "Scanned Collection Count", "Batch Total Time (ms)",
            "Batch Read Time (ms)", "Batch Write Time (ms)",
            "Batch Payloads Processed", "Initial Hasher Docs Rate (docs/sec)",
            "Stream Hasher Buffer Size", "",
        ),
        specs=[
            [{}, {}],  # Row 1: Collection Copy Progress
            [{}, {}],  # Row 2: Collection Copy Durations
            [{}, {}],  # Row 3: Partition Progress
            [{}, {}],  # Row 4: Partition Histograms
            [{}, {}],  # Row 5: Collection Copy Cleanup
            [{}, {}],  # Row 6: Collection Copy Cleanup (continued)
            [{}, {}],  # Row 7: Phase, Lag Time
            [{}, {}],  # Row 8: CPU, Memory
            [{}, {}],  # Row 9: Ping latencies
            [{}, {}],  # Row 10: Src/Dst Unavailable
            [{}, {}],  # Row 11: Verifier Lag, Retry
            [{}, {}],  # Row 12: Events throughput
            [{}, {}],  # Row 13: Bytes read, DDL
            [{}, {}],  # Row 14: CEA durations
            [{}, {}],  # Row 15: Transaction metrics
            [{}, {}],  # Row 16: CEA CRUD single
            [{}, {}],  # Row 17: CEA CRUD errors
            [{}, {}],  # Row 18: CEA CRUD refetch/apply
            [{}, {}],  # Row 19: CEA CRUD events
            [{}, {}],  # Row 20: CEA CRUD LWS
            [{}, {}],  # Row 21: CEA Channel util
            [{}, {}],  # Row 22: CEA Spread
            [{}, {}],  # Row 23: Hot docs read/refetch
            [{}, {}],  # Row 24: Hot docs apply/skipped
            [{}, {}],  # Row 25: Indexes
            [{}, {}],  # Row 26: Buffer Service throughput
            [{}, {}],  # Row 27: Buffer Service insert
            [{}, {}],  # Row 28: Buffer Service doc size
            [{}, {}],  # Row 29: Bulk Inserter throughput
            [{}, {}],  # Row 30: Bulk Inserter batch size
            [{}, {}],  # Row 31: Verifier auditor
            [{}, {}],  # Row 32: Verifier scanned, batch total
            [{}, {}],  # Row 33: Verifier batch read/write
            [{}, {}],  # Row 34: Verifier payloads, initial hasher
            [{}, {}],  # Row 35: Verifier stream hasher
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
    
    # Helper to add counter rate trace
    def add_counter_rate(row, col, metric_name, trace_name, legend_group, no_data_label):
        times, values = collector.get_counter_rate(metric_name)
        if times:
            fig.add_trace(
                go.Scattergl(x=times, y=values, mode='lines', name=trace_name,
                            legendgroup=legend_group),
                row=row, col=col
            )
        else:
            add_no_data(row, col, no_data_label)
    
    # Helper to add gauge trace
    def add_gauge(row, col, metric_name, trace_name, legend_group, no_data_label):
        times, values = collector.get_gauge_series(metric_name)
        if times:
            fig.add_trace(
                go.Scattergl(x=times, y=values, mode='lines', name=trace_name,
                            legendgroup=legend_group),
                row=row, col=col
            )
        else:
            add_no_data(row, col, no_data_label)
    
    # ==================== ROWS 1-4: COLLECTION COPY & PARTITION ====================
    
    # Row 1: Docs/Bytes Copied Rate
    add_counter_rate(1, 1, 'mongosync_collection_copy_copied_docs_count', 'Docs/sec', 'groupDocsCopied', 'Docs Copied Rate')
    add_counter_rate(1, 2, 'mongosync_collection_copy_copied_bytes_count', 'Bytes/sec', 'groupBytesCopied', 'Bytes Copied Rate')
    
    # Row 2: Collection Copy Durations
    add_histogram_percentiles(2, 1, 'mongosync_collection_copy_source_read_op_duration', 'groupCCSourceRead', 'CC Source Read Duration')
    add_histogram_percentiles(2, 2, 'mongosync_collection_copy_destination_write_op_duration', 'groupCCDestWrite', 'CC Dest Write Duration')
    
    # Row 3: Partition Progress
    add_counter_rate(3, 1, 'mongosync_collection_copy_partitions_completed_count', 'Partitions/sec', 'groupPartitionsCompleted', 'Partitions Completed Rate')
    add_gauge(3, 2, 'mongosync_collection_copy_partition_copy_bytes_read_per_second', 'Bytes/sec', 'groupPartitionBytesRead', 'Partition Bytes Read Rate')
    
    # Row 4: Partition Histograms
    add_histogram_percentiles(4, 1, 'mongosync_collection_copy_partition_size', 'groupPartitionSize', 'Partition Size')
    add_histogram_percentiles(4, 2, 'mongosync_collection_copy_copy_partition_duration', 'groupPartitionDuration', 'Partition Copy Duration')
    
    # ==================== ROWS 5-6: COLLECTION COPY CLEANUP ====================
    
    # Row 5: Partitions/Docs Deleted Rate
    add_counter_rate(5, 1, 'mongosync_collection_copy_partitions_deleted_count', 'Partitions/sec', 'groupPartitionsDeleted', 'Partitions Deleted Rate')
    add_counter_rate(5, 2, 'mongosync_collection_copy_partition_copy_docs_deleted_count', 'Docs/sec', 'groupDocsDeleted', 'Docs Deleted Rate')
    
    # Row 6: Bytes Deleted Rate (col 2 is empty placeholder)
    add_counter_rate(6, 1, 'mongosync_collection_copy_partition_copy_bytes_deleted_count', 'Bytes/sec', 'groupBytesDeleted', 'Bytes Deleted Rate')
    add_no_data(6, 2, '')  # Empty placeholder
    
    # ==================== ROWS 7-11: CORE REPLICATION AND PHASE + HOST LOAD ====================
    
    # Row 7: Phase and Lag Time
    add_gauge(7, 1, 'mongosync_phase', 'Phase', 'groupPhase', 'Phase')
    add_gauge(7, 2, 'mongosync_lag_time', 'Lag Time', 'groupLag', 'Lag Time')
    
    # Row 8: CPU and Memory
    add_gauge(8, 1, 'mongosync_host_cpu_usage', 'CPU %', 'groupCPU', 'CPU Usage')
    add_gauge(8, 2, 'mongosync_host_memory_percent_used', 'Memory %', 'groupMemory', 'Memory Usage')
    
    # Row 9: Ping Latencies
    add_histogram_percentiles(9, 1, 'mongosync_src_ping_latency', 'groupSrcPing', 'Source Ping Latency')
    add_histogram_percentiles(9, 2, 'mongosync_dst_ping_latency', 'groupDstPing', 'Destination Ping Latency')
    
    # Row 10: Source/Destination Unavailable
    add_gauge(10, 1, 'mongosync_src_unavailable', 'Unavailable', 'groupSrcUnavail', 'Source Unavailable')
    add_gauge(10, 2, 'mongosync_dst_unavailable', 'Unavailable', 'groupDstUnavail', 'Destination Unavailable')
    
    # Row 11: Verifier Lag and Retry Count
    add_gauge(11, 1, 'verifier_lag_time', 'Verifier Lag', 'groupVerifierLag', 'Verifier Lag Time')
    add_gauge(11, 2, 'mongosync_retry_count', 'Retries', 'groupRetry', 'Retry Count')
    
    # ==================== ROWS 12-13: CEA READER & OVERALL ====================
    
    # Row 12: Events Read/Applied Rate
    add_counter_rate(12, 1, 'mongosync_cea_change_stream_reader_events_read', 'Events/sec', 'groupEventsRead', 'Events Read Rate')
    add_counter_rate(12, 2, 'mongosync_cea_total_events_applied', 'Events/sec', 'groupEventsApplied', 'Events Applied Rate')
    
    # Row 13: Bytes Read Rate and DDL Events
    add_counter_rate(13, 1, 'mongosync_cea_change_stream_reader_bytes_read', 'Bytes/sec', 'groupBytesRead', 'Bytes Read Rate')
    add_counter_rate(13, 2, 'mongosync_cea_total_ddl_events_applied', 'Events/sec', 'groupDDLEvents', 'DDL Events Applied Rate')
    
    # ==================== ROWS 14-15: CEA DURATIONS ====================
    
    # Row 14: CEA Destination Write and Source Read Duration
    add_histogram_percentiles(14, 1, 'mongosync_cea_destination_write_op_duration', 'groupCEADstWrite', 'CEA Destination Write Duration')
    add_histogram_percentiles(14, 2, 'mongosync_cea_source_read_op_duration', 'groupCEASrcRead', 'CEA Source Read Duration')
    
    # Row 15: Transaction Duration and Size
    add_histogram_percentiles(15, 1, 'mongosync_cea_crud_applier_txn_duration', 'groupTxnDuration', 'Transaction Duration')
    add_histogram_percentiles(15, 2, 'mongosync_cea_crud_applier_txn_size', 'groupTxnSize', 'Transaction Size')
    
    # ==================== ROWS 16-22: CEA CRUD APPLIER ====================
    
    # Row 16: Single Event Count and Single Write Duration
    add_counter_rate(16, 1, 'mongosync_cea_crud_applier_single_count', 'Events/sec', 'groupSingleCount', 'Single Event Count Rate')
    add_histogram_percentiles(16, 2, 'mongosync_cea_crud_applier_single_write_duration', 'groupSingleWrite', 'Single Write Duration')
    
    # Row 17: Duplicate Key Errors and One-by-One Events
    add_counter_rate(17, 1, 'mongosync_cea_crud_applier_duplicate_key_errors_count', 'Errors/sec', 'groupDupKey', 'Duplicate Key Errors Rate')
    add_counter_rate(17, 2, 'mongosync_cea_crud_applier_one_by_one_events_count', 'Events/sec', 'groupOneByOne', 'One-by-One Events Rate')
    
    # Row 18: Default Errors and Refetch Duration
    add_counter_rate(18, 1, 'mongosync_cea_crud_applier_default_error_count', 'Errors/sec', 'groupDefaultErr', 'Default Errors Rate')
    add_histogram_percentiles(18, 2, 'mongosync_cea_crud_applier_refetch_duration', 'groupRefetch', 'Refetch Duration')
    
    # Row 19: Apply Event Duration and Total CRUD Events
    add_histogram_percentiles(19, 1, 'mongosync_cea_crud_applier_apply_event_duration', 'groupApplyEvent', 'Apply Event Duration')
    add_counter_rate(19, 2, 'mongosync_cea_total_crud_events_applied', 'Events/sec', 'groupTotalCRUD', 'Total CRUD Events Rate')
    
    # Row 20: LWS Get/Set Entry Duration
    add_histogram_percentiles(20, 1, 'mongosync_cea_crud_applier_lws_get_entry_duration', 'groupLWSGet', 'LWS Get Entry Duration')
    add_histogram_percentiles(20, 2, 'mongosync_cea_crud_applier_lws_set_entry_duration', 'groupLWSSet', 'LWS Set Entry Duration')
    
    # Row 21: Channel Utilization
    add_gauge(21, 1, 'mongosync_cea_reader_to_dispatcher_aggregate_channel_utilization', 'Utilization', 'groupReaderDispatcher', 'Reader-Dispatcher Channel Util')
    add_gauge(21, 2, 'mongosync_cea_dispatcher_to_processor_aggregate_channel_utilization', 'Utilization', 'groupDispatcherProcessor', 'Dispatcher-Processor Channel Util')
    
    # Row 22: Spread Disparity (col 2 is empty placeholder)
    add_gauge(22, 1, 'mongosync_cea_spread_disparity', 'Disparity', 'groupSpread', 'Spread Disparity')
    add_no_data(22, 2, '')  # Empty placeholder
    
    # ==================== ROWS 23-24: HOT DOCUMENTS ====================
    
    # Row 23: Hot Doc States Read and Refetch Duration
    add_histogram_percentiles(23, 1, 'mongosync_hot_doc_states_read_op_duration', 'groupHotDocRead', 'Hot Doc States Read Duration')
    add_histogram_percentiles(23, 2, 'mongosync_hot_doc_refetch_op_duration', 'groupHotDocRefetch', 'Hot Doc Refetch Duration')
    
    # Row 24: Hot Doc Apply Duration and Events Skipped
    add_histogram_percentiles(24, 1, 'mongosync_hot_doc_apply_op_duration', 'groupHotDocApply', 'Hot Doc Apply Duration')
    add_counter_rate(24, 2, 'mongosync_cea_total_hot_doc_crud_events_skipped', 'Events/sec', 'groupHotDocSkipped', 'Hot Doc Events Skipped Rate')
    
    # ==================== ROW 25: INDEXES ====================
    
    # Row 25: Index Create Duration and Indexes Created
    add_histogram_percentiles(25, 1, 'mongosync_index_checker_service_create_indexes_duration', 'groupIndexCreate', 'Index Create Duration')
    add_counter_rate(25, 2, 'mongosync_index_checker_service_created_count', 'Indexes/sec', 'groupIndexesCreated', 'Indexes Created Rate')
    
    # ==================== ROWS 26-28: BUFFER SERVICE ====================
    
    # Row 26: Buffer Docs/Bytes Processed Rate
    add_counter_rate(26, 1, 'mongosync_buffer_service_docs_processed_count', 'Docs/sec', 'groupBufDocs', 'Buffer Docs Processed Rate')
    add_counter_rate(26, 2, 'mongosync_buffer_service_bytes_processed_count', 'Bytes/sec', 'groupBufBytes', 'Buffer Bytes Processed Rate')
    
    # Row 27: Buffer Insert Duration and Doc Buffers in Channel
    add_histogram_percentiles(27, 1, 'mongosync_buffer_service_insert_duration', 'groupBufInsertDur', 'Buffer Insert Duration')
    add_gauge(27, 2, 'mongosync_buffer_service_doc_buffers_in_channel_count', 'Buffers', 'groupBufChannel', 'Doc Buffers in Channel')
    
    # Row 28: Document Size and Buffer Insertions Rate
    add_histogram_percentiles(28, 1, 'mongosync_buffer_service_doc_size', 'groupDocSize', 'Document Size')
    add_counter_rate(28, 2, 'mongosync_buffer_service_insertions_count', 'Insertions/sec', 'groupBufInsertions', 'Buffer Insertions Rate')
    
    # ==================== ROWS 29-30: BULK INSERTER ====================
    
    # Row 29: Bulk Inserter Docs/Bytes Rate
    add_counter_rate(29, 1, 'mongosync_bulk_inserter_docs_inserted_count', 'Docs/sec', 'groupBulkDocs', 'Bulk Inserter Docs Rate')
    add_counter_rate(29, 2, 'mongosync_bulk_inserter_bytes_inserted_count', 'Bytes/sec', 'groupBulkBytes', 'Bulk Inserter Bytes Rate')
    
    # Row 30: Docs Per Batch and Bytes Per Batch
    add_histogram_percentiles(30, 1, 'mongosync_bulk_inserter_docs_per_batch', 'groupDocsPerBatch', 'Docs Per Batch')
    add_histogram_percentiles(30, 2, 'mongosync_bulk_inserter_bytes_per_batch', 'groupBytesPerBatch', 'Bytes Per Batch')
    
    # ==================== ROWS 31-35: VERIFIER ====================
    
    # Row 31: Verifier Docs Hashed and Estimated Doc Count
    add_gauge(31, 1, 'verifier_auditor_num_docs_hashed', 'Docs Hashed', 'groupDocsHashed', 'Verifier Docs Hashed')
    add_gauge(31, 2, 'verifier_auditor_estimated_docs_count', 'Estimated Docs', 'groupEstDocs', 'Verifier Estimated Doc Count')
    
    # Row 32: Scanned Collection Count and Batch Total Time
    add_gauge(32, 1, 'verifier_auditor_scanned_collection_count', 'Collections', 'groupScannedColl', 'Scanned Collection Count')
    add_histogram_percentiles(32, 2, 'verifier_batch_writer_handle_batch_total_time', 'groupBatchTotal', 'Batch Total Time')
    
    # Row 33: Batch Read Time and Batch Write Time
    add_histogram_percentiles(33, 1, 'verifier_batch_writer_handle_batch_read_time', 'groupBatchRead', 'Batch Read Time')
    add_histogram_percentiles(33, 2, 'verifier_batch_writer_handle_batch_write_time', 'groupBatchWrite', 'Batch Write Time')
    
    # Row 34: Batch Payloads Processed and Initial Hasher Docs Rate
    add_histogram_percentiles(34, 1, 'verifier_batch_writer_handle_batch_payloads_processed_total', 'groupVerifierPayloads', 'Batch Payloads Processed')
    add_counter_rate(34, 2, 'verifier_initial_hasher_docs_hashed_total', 'Docs/sec', 'groupHasherDocs', 'Initial Hasher Docs Rate')
    
    # Row 35: Stream Hasher Buffer Size (col 2 is empty placeholder)
    add_gauge(35, 1, 'verifier_stream_hasher_buffer_size', 'Buffer Size', 'groupStreamBuf', 'Stream Hasher Buffer Size')
    add_no_data(35, 2, '')  # Empty placeholder
    
    # Update layout
    fig.update_layout(
        height=7875,
        width=1450,
        title_text="Mongosync Metrics",
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
        for row in range(1, 36):
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
