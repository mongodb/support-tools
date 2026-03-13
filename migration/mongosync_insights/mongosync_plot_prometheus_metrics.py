"""
Prometheus metrics parsing and plotting for mongosync_metrics.log files.
Parses Prometheus exposition format metrics embedded in JSON log lines.
Plots are dynamically generated from mongosync_metrics.json configuration.
"""
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from plotly.subplots import make_subplots
import json
import re
import logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict, OrderedDict
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

# Path to metrics configuration file
CONFIG_PATH = Path(__file__).parent / 'mongosync_metrics.json'


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


def load_metrics_config(config_path: Path = None) -> List[Dict[str, Any]]:
    """Load metrics configuration from JSON file."""
    if config_path is None:
        config_path = CONFIG_PATH
    
    with open(config_path) as f:
        return json.load(f)


def generate_title(metric: Dict[str, Any]) -> str:
    """
    Generate a plot title for a metric.
    Uses the 'title' field if present, otherwise auto-generates from name and unit.
    """
    if 'title' in metric:
        base_title = metric['title']
    else:
        # Convert metric name to readable title
        name = metric['name']
        for prefix in ['mongosync_', 'verifier_']:
            if name.startswith(prefix):
                name = name[len(prefix):]
        base_title = ' '.join(word.capitalize() for word in name.split('_'))
    
    # Add unit suffix
    unit = metric.get('unit', '')
    unit_map = {
        'milliseconds': 'ms',
        'seconds': 'sec',
        'bytes': 'bytes',
        'bytes_per_second': 'bytes/sec',
        'percent': '%',
        'documents': 'docs',
        'events': 'events',
        'count': '',
        'ratio': '',
        'boolean': '',
        'enum': '',
        'errors': 'errors',
        'indexes': 'indexes',
        'collections': 'collections',
        'payloads': 'payloads'
    }
    suffix = unit_map.get(unit, unit)
    
    if suffix:
        return f"{base_title} ({suffix})"
    return base_title


def add_no_data(fig, row: int, col: int, name: str):
    """Add a NO DATA placeholder to a subplot."""
    fig.add_trace(
        go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name=name,
                  textfont=dict(size=30, color="black")),
        row=row, col=col
    )
    fig.update_yaxes(range=[-1, 1], row=row, col=col)
    fig.update_xaxes(range=[-1, 1], row=row, col=col)


def add_gauge_trace(fig, collector: MetricsCollector, row: int, col: int, 
                    metric_name: str, legend_group: str, no_data_label: str):
    """Add a gauge metric trace to the figure."""
    times, values = collector.get_gauge_series(metric_name)
    if times:
        fig.add_trace(
            go.Scattergl(x=times, y=values, mode='lines', name='Value',
                        legendgroup=legend_group),
            row=row, col=col
        )
    else:
        add_no_data(fig, row, col, no_data_label)


def add_counter_rate_trace(fig, collector: MetricsCollector, row: int, col: int,
                           metric_name: str, legend_group: str, no_data_label: str):
    """Add a counter rate metric trace to the figure."""
    times, values = collector.get_counter_rate(metric_name)
    if times:
        fig.add_trace(
            go.Scattergl(x=times, y=values, mode='lines', name='Rate',
                        legendgroup=legend_group),
            row=row, col=col
        )
    else:
        add_no_data(fig, row, col, no_data_label)


def add_histogram_percentiles_trace(fig, collector: MetricsCollector, row: int, col: int,
                                    metric_name: str, legend_group: str, no_data_label: str):
    """Add histogram percentile traces (p50, p95, p99) to the figure."""
    pcts = collector.get_histogram_percentiles(metric_name, [50, 95, 99])
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
        add_no_data(fig, row, col, no_data_label)


def plot_metric(fig, collector: MetricsCollector, metric: Dict[str, Any], row: int, col: int):
    """Plot a single metric based on its type."""
    name = metric['name']
    mtype = metric['type']
    legend_group = f"group_{name}"
    title = generate_title(metric)
    
    if mtype == 'gauge':
        add_gauge_trace(fig, collector, row, col, name, legend_group, title)
    elif mtype == 'counter':
        add_counter_rate_trace(fig, collector, row, col, name, legend_group, title)
    elif mtype == 'histogram':
        add_histogram_percentiles_trace(fig, collector, row, col, name, legend_group, title)
    else:
        logger.warning(f"Unknown metric type '{mtype}' for metric '{name}'")
        add_no_data(fig, row, col, title)


def create_metrics_plots(collector: MetricsCollector, config_path: Path = None) -> str:
    """
    Create Plotly plots for the collected Prometheus metrics.
    Plots are dynamically generated from the metrics configuration JSON.
    
    Args:
        collector: MetricsCollector instance with parsed data
        config_path: Optional path to metrics config JSON (defaults to mongosync_metrics.json)
        
    Returns:
        JSON string of the Plotly figure
    """
    logger.info(f"Creating metrics plots from {collector.metrics_count} metric points")
    
    # Load configuration
    metrics_config = load_metrics_config(config_path)
    
    # Filter enabled metrics (default: enabled)
    enabled_metrics = [m for m in metrics_config if m.get('enabled', True)]
    
    # Group metrics by section while preserving order
    sections = OrderedDict()
    for m in enabled_metrics:
        section = m['section']
        if section not in sections:
            sections[section] = []
        sections[section].append(m)
    
    # Build flat list with None placeholders for sections with odd counts
    # This keeps each section visually separated in the 2-column grid
    flat_items = []  # List of metric dicts or None (for empty cells)
    for section_name, metrics in sections.items():
        for m in metrics:
            flat_items.append(m)
        # Add placeholder if section has odd count (fills remaining cell in row)
        if len(metrics) % 2 == 1:
            flat_items.append(None)
    
    total_cells = len(flat_items)
    
    if total_cells == 0:
        logger.warning("No metrics configured for plotting")
        return ""
    
    # Calculate grid dimensions (2 columns)
    rows = (total_cells + 1) // 2
    
    # Generate subplot titles (empty string for placeholders)
    titles = []
    for item in flat_items:
        if item is None:
            titles.append('')
        else:
            titles.append(generate_title(item))
    
    # Create subplots
    fig = make_subplots(
        rows=rows, 
        cols=2,
        subplot_titles=titles,
        specs=[[{}, {}] for _ in range(rows)]
    )
    
    # Plot each metric, tracking empty cells
    empty_cells = []  # Track (row, col) of empty cells to hide
    row, col = 1, 1
    for item in flat_items:
        if item is None:
            empty_cells.append((row, col))
        else:
            plot_metric(fig, collector, item, row, col)
        col += 1
        if col > 2:
            col = 1
            row += 1
    
    # Hide all empty cells (sections with odd counts)
    for r, c in empty_cells:
        fig.update_xaxes(visible=False, row=r, col=c)
        fig.update_yaxes(visible=False, row=r, col=c)
    
    # Update layout
    fig.update_layout(
        height=rows * 225,
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
        for r in range(1, rows + 1):
            for c in range(1, 3):
                fig.update_xaxes(range=[global_min_date, global_max_date], row=r, col=c)
    
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
