import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from plotly.subplots import make_subplots
from tqdm import tqdm
from flask import request, render_template
import json
import uuid as uuid_mod
from collections import deque
from datetime import datetime, timezone
from dateutil import parser
import re
import logging
import os
import mimetypes
from werkzeug.utils import secure_filename
from .utils import format_byte_size, convert_bytes
from .app_config import (
    MAX_FILE_SIZE, ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES,
    load_error_patterns, classify_file_type,
    LOG_VIEWER_MAX_LINES, LOG_STORE_DIR,
)
from .file_decompressor import decompress_file_classified, is_compressed_mime_type
from .otel_metrics import MetricsCollector, create_metrics_plots
from .log_store import LogStore
from .log_store_registry import log_store_registry
from .snapshot_store import save_snapshot


def detect_mime_type(file_sample: bytes, filename: str) -> str:
    """
    Detect MIME type using magic bytes and file extension.
    Pure-Python replacement for python-magic — no system libmagic needed.
    """
    if file_sample[:2] == b'\x1f\x8b':
        return 'application/gzip'
    if file_sample[:4] == b'PK\x03\x04':
        return 'application/zip'
    if file_sample[:3] == b'BZh':
        return 'application/x-bzip2'
    if len(file_sample) >= 262 and file_sample[257:262] == b'ustar':
        return 'application/x-tar'

    mime_type, _ = mimetypes.guess_type(filename)
    if mime_type:
        return mime_type

    try:
        file_sample.decode('utf-8')
        return 'text/plain'
    except UnicodeDecodeError:
        return 'application/octet-stream'

def upload_file():
    # Use the centralized logging configuration
    logger = logging.getLogger(__name__)
    
    # Check if a file was uploaded
    if 'file' not in request.files:
        logger.error("No file was uploaded")
        return render_template('error.html', 
                             error_title="Upload Error",
                             error_message="No file was selected for upload.")

    file = request.files['file']

    # If the user does not select a file, the browser submits an
    # empty file without a filename.
    if file.filename == '':
        logger.error("Empty file without a filename")
        return render_template('error.html',
                             error_title="Upload Error", 
                             error_message="Please select a file to upload.")

    if file:
        # Validate filename and extension
        filename = secure_filename(file.filename)
        if not filename:
            logger.error("Invalid filename")
            return render_template('error.html',
                                 error_title="Upload Error",
                                 error_message="Invalid filename. Please use a valid file name.")
        
        # Check file extension
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            logger.error(f"Invalid file extension: {file_ext}. Allowed: {ALLOWED_EXTENSIONS}")
            return render_template('error.html',
                                 error_title="Invalid File Type",
                                 error_message=f"File type '{file_ext}' is not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}")
        
        # Check file size (Flask's request.files doesn't have content_length, so we need to read and check)
        file.seek(0, 2)  # Seek to end of file
        file_size = file.tell()  # Get current position (file size)
        file.seek(0)  # Reset to beginning
        
        if file_size > MAX_FILE_SIZE:
            logger.error(f"File too large: {file_size} bytes (max: {MAX_FILE_SIZE} bytes)")
            max_size_mb = MAX_FILE_SIZE / (1024 * 1024)
            actual_size_mb = file_size / (1024 * 1024)
            return render_template('error.html',
                                 error_title="File Too Large",
                                 error_message=f"File size ({actual_size_mb:.1f} MB) exceeds maximum allowed size ({max_size_mb:.1f} MB).")
        
        # Detect MIME type using magic bytes and file extension (no libmagic needed)
        file.seek(0)
        file_sample = file.read(2048)
        file_mime_type = detect_mime_type(file_sample, filename)
        file.seek(0)

        logger.info(f"Detected MIME type: {file_mime_type}")

        if file_mime_type not in ALLOWED_MIME_TYPES:
            logger.error(f"Invalid MIME type: {file_mime_type}. Allowed: {ALLOWED_MIME_TYPES}")
            return render_template('error.html',
                                 error_title="Invalid File Type",
                                 error_message=f"File MIME type '{file_mime_type}' is not allowed. Only JSON/text files are accepted. Detected type: {file_mime_type}")
        
        logger.info(f"File validation passed: {filename} ({file_size} bytes, {file_ext}, MIME: {file_mime_type})")
        # Optimized single-pass log parsing with streaming approach
        logger.info("Starting optimized log parsing - single pass through file")
        
        # Pre-compile all regex patterns once
        patterns = {
            'replication_progress': re.compile(r"Replication progress", re.IGNORECASE),
            'version_info': re.compile(r"Version info", re.IGNORECASE),
            'operation_stats': re.compile(r"Operation duration stats", re.IGNORECASE),
            'sent_response': re.compile(r"sent response", re.IGNORECASE),
            'phase_transitions': re.compile(r"Starting initializing collections and indexes phase|Starting initializing partitions phase|Starting collection copy phase|Starting change event application phase|Commit handler called", re.IGNORECASE),
            'mongosync_options': re.compile(r"Mongosync Options", re.IGNORECASE),
            'hidden_flags': re.compile(r"Mongosync HiddenFlags", re.IGNORECASE),
            'crud_events_rate': re.compile(r"Average Source CRUD events rate", re.IGNORECASE),
            'partition_copy_progress': re.compile(r"Completed writing \d+ / \d+ partitions to destination cluster", re.IGNORECASE),
            'natural_order_collections': re.compile(r"Selected for natural order collection reads", re.IGNORECASE),
            'received_request': re.compile(r"Received request", re.IGNORECASE),
            'partition_single_created': re.compile(r"Creating a single partition for whole collection", re.IGNORECASE),
            'partition_multi_created': re.compile(r"Creating initial partitions for non-capped collection", re.IGNORECASE),
            'partition_sampling_info': re.compile(r"Pre-sampling information", re.IGNORECASE),
            'partition_persisted_after_sampling': re.compile(r"Persisted a new partition after sampling", re.IGNORECASE),
        }
        
        # Load error patterns from external file
        error_patterns_config = load_error_patterns()
        error_patterns = [
            {
                'pattern': re.compile(ep['pattern'], re.IGNORECASE),
                'friendly_name': ep['friendly_name']
            }
            for ep in error_patterns_config
        ]
        
        # Initialize result containers for logs
        data = []
        version_info_list = []
        mongosync_ops_stats = []
        mongosync_sent_response = []
        phase_transitions_json = []
        mongosync_opts_list = []
        mongosync_hiddenflags = []
        mongosync_crud_rate = []
        mongosync_partition_progress = []
        matched_errors = []
        natural_order_collections = []
        mongosync_start_options = []
        partition_single_created = []
        partition_multi_created = []
        partition_sampling_info = []
        partition_persisted_after_sampling = []
        verifier_dst_lag_items = []
        verifier_src_lag_items = []
        
        # Initialize metrics collector for prometheus metrics
        metrics_collector = MetricsCollector()
        
        # Initialize log viewer: tail buffer + SQLite store for full-text search
        raw_log_tail = deque(maxlen=LOG_VIEWER_MAX_LINES)
        store_id = str(uuid_mod.uuid4())
        db_path = os.path.join(LOG_STORE_DIR, f'mi_logstore_{store_id}.db')
        log_store = LogStore(db_path)
        
        # Single pass through the file with streaming
        line_count = 0
        logs_line_count = 0
        metrics_line_count = 0
        invalid_json_count = 0
        
        # Reset file pointer to beginning
        file.seek(0)
        
        # Determine if file is compressed and get appropriate iterator
        # Use classified decompressor to track file types from archives
        if is_compressed_mime_type(file_mime_type):
            logger.info(f"Decompressing {file_mime_type} file before processing (with classification)")
            file_iterator = decompress_file_classified(file, file_mime_type, filename)
            use_classified = True
        else:
            # For non-compressed files, classify by filename
            file_type = classify_file_type(filename)
            if file_type is None:
                file_type = 'logs'
            logger.info(f"Non-compressed file classified as: {file_type}")
            file_iterator = file
            use_classified = False
        
        for item in tqdm(file_iterator, desc="Processing log file"):
            line_count += 1
            
            # Handle classified vs non-classified iterators
            if use_classified:
                line, current_file_type = item
            else:
                line = item
                current_file_type = file_type
            
            # Handle both bytes and string input (decompressed files return bytes)
            if isinstance(line, bytes):
                line = line.decode('utf-8', errors='replace')
            line = line.strip()
            
            if not line:  # Skip empty lines
                continue
            
            # Skip lines that don't look like JSON objects (handles trailing garbage from decompression)
            if not line.startswith('{'):
                continue
            
            # Route to appropriate parser based on file type
            if current_file_type == 'metrics':
                # Process as Prometheus metrics
                metrics_line_count += 1
                metrics_collector.process_line(line)
                continue
            elif current_file_type == 'logs':
                logs_line_count += 1
            else:
                continue
                
            try:
                # Parse JSON only once per line (for logs)
                json_obj = json.loads(line)
                message = json_obj.get('message', '')
                
                # Collect for log viewer: tail buffer + SQLite store
                raw_log_tail.append(line)
                log_store.insert_line(line, parsed=json_obj)
                
                # Apply all filters to the same parsed object
                if patterns['replication_progress'].search(message):
                    data.append(json_obj)
                
                if patterns['version_info'].search(message):
                    version_info_list.append(json_obj)
                
                if patterns['operation_stats'].search(message):
                    mongosync_ops_stats.append(json_obj)
                
                if patterns['sent_response'].search(message):
                    mongosync_sent_response.append(json_obj)
                
                if patterns['phase_transitions'].search(message):
                    phase_transitions_json.append(json_obj)
                
                if patterns['mongosync_options'].search(message):
                    # Filter out time and level fields for options
                    filtered_obj = {k: v for k, v in json_obj.items() if k not in ('time', 'level')}
                    mongosync_opts_list.append(filtered_obj)
                
                if patterns['hidden_flags'].search(message):
                    # Filter out time and level fields for hidden flags
                    filtered_obj = {k: v for k, v in json_obj.items() if k not in ('time', 'level')}
                    mongosync_hiddenflags.append(filtered_obj)
                
                if patterns['received_request'].search(message) and json_obj.get('uri') == '/api/v1/start':
                    try:
                        body = json.loads(json_obj.get('body', '{}'))
                        mongosync_start_options.append(body)
                    except (json.JSONDecodeError, TypeError):
                        pass
                
                if patterns['crud_events_rate'].search(message):
                    mongosync_crud_rate.append(json_obj)
                
                if patterns['partition_copy_progress'].search(message):
                    mongosync_partition_progress.append(json_obj)
                
                reason = json_obj.get('reason', '')
                if patterns['natural_order_collections'].search(reason):
                    db = json_obj.get('database', '')
                    coll = json_obj.get('collection', '')
                    if db and coll:
                        natural_order_collections.append({'database': db, 'collection': coll})
                
                if patterns['partition_single_created'].search(message):
                    partition_single_created.append(json_obj)
                
                if patterns['partition_multi_created'].search(message):
                    partition_multi_created.append(json_obj)
                
                if patterns['partition_sampling_info'].search(message):
                    partition_sampling_info.append(json_obj)
                
                if patterns['partition_persisted_after_sampling'].search(message):
                    partition_persisted_after_sampling.append(json_obj)
                
                if json_obj.get('verifierDstLagTimeSeconds') is not None and 'time' in json_obj:
                    verifier_dst_lag_items.append(json_obj)
                
                if json_obj.get('verifierSrcLagTimeSeconds') is not None and 'time' in json_obj:
                    verifier_src_lag_items.append(json_obj)
                
                # Check for common error patterns
                for ep in error_patterns:
                    if ep['pattern'].search(message):
                        matched_errors.append({
                            'friendly_name': ep['friendly_name'],
                            'message': message,
                            'time': json_obj.get('time', ''),
                            'level': json_obj.get('level', ''),
                            'full_log': json.dumps(json_obj, indent=2)
                        })
                        break  # Only match first pattern per message
                    
            except json.JSONDecodeError as e:
                invalid_json_count += 1
                if invalid_json_count <= 5:  # Log first 5 errors to avoid spam
                    logger.warning(f"Invalid JSON on line {line_count}: {e}")
                # Only treat as fatal error if this is the first error AND we haven't processed any valid lines
                if invalid_json_count == 1 and logs_line_count == 0 and metrics_line_count == 0:
                    logger.error(f"File appears to contain invalid JSON. First error on line {line_count}: {e}")
                    return render_template('error.html',
                                         error_title="Invalid File Format",
                                         error_message=f"The uploaded file does not contain valid JSON format. Error on line {line_count}: {str(e)}. Please ensure you're uploading a valid mongosync log file in NDJSON format.")
        
        # Finalize log store: flush remaining buffered rows and build FTS index
        log_store.flush()
        if log_store.total_documents > 0:
            log_store.build_fts_index()
            log_store_registry.register(store_id, db_path)
            logger.info(f"Log store ready: {log_store.total_documents} documents, store_id={store_id[:8]}...")
        else:
            log_store.delete()
            store_id = ''
        
        logger.info(f"Processed {line_count} total lines ({logs_line_count} logs, {metrics_line_count} metrics), found {invalid_json_count} invalid JSON lines")
        logger.info(f"Found: {len(data)} replication progress, {len(version_info_list)} version info, "
                    f"{len(mongosync_ops_stats)} operation stats, {len(mongosync_sent_response)} sent responses, "
                    f"{len(phase_transitions_json)} phase transitions, {len(mongosync_opts_list)} options, "
                    f"{len(mongosync_hiddenflags)} hidden flags, {len(mongosync_crud_rate)} CRUD rate entries, "
                    f"{len(mongosync_partition_progress)} partition progress entries, "
                    f"{len(natural_order_collections)} natural order collections, "
                    f"{len(matched_errors)} common errors")
        logger.info(f"Metrics collector: {metrics_collector.metrics_count} metric points from {metrics_collector.line_count} lines")  
        
        has_any_log_data = (len(data) > 0 or len(version_info_list) > 0 or len(mongosync_ops_stats) > 0 or
                            len(mongosync_sent_response) > 0 or len(phase_transitions_json) > 0 or
                            len(mongosync_partition_progress) > 0 or len(mongosync_crud_rate) > 0)
        has_any_metrics_data = metrics_collector.metrics_count > 0
        if not has_any_log_data and not has_any_metrics_data:
            logger.warning(f"No recognizable mongosync data found in {filename} ({line_count} lines processed)")
            return render_template('error.html',
                                 error_title="No Mongosync Data Found",
                                 error_message=f"The file '{filename}' was processed ({line_count:,} lines) but no recognizable "
                                               f"mongosync log entries or metrics were found. Please ensure you are uploading a "
                                               f"valid mongosync log file (NDJSON format with standard mongosync log messages).")

        # Sort log data by timestamp to ensure correct chronological plot ordering
        # (archives may contain rotated log files in non-chronological order)
        data.sort(key=lambda x: x.get('time', ''))
        mongosync_ops_stats.sort(key=lambda x: x.get('time', ''))
        mongosync_crud_rate.sort(key=lambda x: x.get('time', ''))
        mongosync_partition_progress.sort(key=lambda x: x.get('time', ''))
        mongosync_sent_response.sort(key=lambda x: x.get('time', ''))
        verifier_dst_lag_items.sort(key=lambda x: x.get('time', ''))
        verifier_src_lag_items.sort(key=lambda x: x.get('time', ''))

        # Aggregate partition initialization data per collection
        partition_init_data = []
        if partition_single_created or partition_multi_created or partition_sampling_info or partition_persisted_after_sampling:
            pi_map = {}  # keyed by (db, coll)

            for item in partition_single_created:
                db = item.get('database', '')
                coll = item.get('collection', '')
                key = (db, coll)
                if key not in pi_map:
                    pi_map[key] = {}
                reason = item.get('reason', '')
                pi_map[key]['type'] = 'Natural Order' if 'natural order' in reason.lower() else 'Capped'
                pi_map[key]['reason'] = reason
                pi_map[key]['partition_count'] = 1
                pi_map[key]['init_started'] = item.get('time', '')
                pi_map[key]['init_ended'] = item.get('time', '')
                pi_map[key].setdefault('sampler', 'N/A')
                pi_map[key].setdefault('doc_count', None)
                pi_map[key].setdefault('expected_partition_size', None)
                pi_map[key].setdefault('ids_sampled', None)

            for item in partition_multi_created:
                db = item.get('database', '')
                coll = item.get('collection', '')
                key = (db, coll)
                if key not in pi_map:
                    pi_map[key] = {}
                pi_map[key]['type'] = 'Sampled (multi-partition)'
                pi_map[key]['reason'] = 'Index sampled'
                pi_map[key].setdefault('partition_count', 0)
                pi_map[key]['init_started'] = item.get('time', '')
                pi_map[key]['expected_partition_size'] = item.get('expectedSizePerPartition')

            for item in partition_sampling_info:
                db = item.get('database', '')
                coll = item.get('collection', '')
                key = (db, coll)
                if key not in pi_map:
                    pi_map[key] = {}
                pi_map[key]['sampler'] = item.get('sampler', 'N/A')
                pi_map[key]['doc_count'] = item.get('collectionDocCount')
                pi_map[key]['ids_sampled'] = item.get('numIDsToSample')

            for item in partition_persisted_after_sampling:
                coll = item.get('collection', '')
                p = item.get('partition', {})
                ns = p.get('partition', {})
                db = ns.get('db', '')
                if not coll:
                    coll = ns.get('coll', '')
                key = (db, coll)
                if key not in pi_map:
                    pi_map[key] = {}
                pi_map[key]['partition_count'] = pi_map[key].get('partition_count', 0) + 1
                ts = item.get('time', '')
                if ts > pi_map[key].get('init_ended', ''):
                    pi_map[key]['init_ended'] = ts

            for (db, coll), info in sorted(pi_map.items()):
                started = info.get('init_started', '')
                ended = info.get('init_ended', started)
                duration_sec = None
                if started and ended:
                    try:
                        t0 = datetime.strptime(started[:26], "%Y-%m-%dT%H:%M:%S.%f")
                        t1 = datetime.strptime(ended[:26], "%Y-%m-%dT%H:%M:%S.%f")
                        duration_sec = round((t1 - t0).total_seconds(), 2)
                    except (ValueError, TypeError):
                        pass
                exp_size = info.get('expected_partition_size')
                exp_size_display = f"{exp_size / (1024*1024):.0f} MB" if exp_size else 'N/A'
                partition_init_data.append({
                    'collection': f"{db}.{coll}",
                    'type': info.get('type', 'Unknown'),
                    'reason': info.get('reason', ''),
                    'partition_count': info.get('partition_count', 0),
                    'doc_count': info.get('doc_count'),
                    'expected_partition_size': exp_size_display,
                    'sampler': info.get('sampler', 'N/A'),
                    'ids_sampled': info.get('ids_sampled'),
                    'init_started': started[:26] if started else '',
                    'init_ended': ended[:26] if ended else '',
                    'duration_sec': duration_sec,
                })
            logger.info(f"Aggregated partition init data for {len(partition_init_data)} collections")

        # Build partition init progress time series (in-progress and completed per collection over time)
        partition_init_progress_times = []
        partition_init_progress_in_progress = []
        partition_init_progress_completed = []
        if partition_init_data:
            init_events = []
            for d in partition_init_data:
                if d['init_started']:
                    try:
                        t0 = datetime.strptime(d['init_started'][:26], "%Y-%m-%dT%H:%M:%S.%f")
                        init_events.append((t0, 'start'))
                    except (ValueError, TypeError):
                        pass
                if d['init_ended']:
                    try:
                        t1 = datetime.strptime(d['init_ended'][:26], "%Y-%m-%dT%H:%M:%S.%f")
                        init_events.append((t1, 'end'))
                    except (ValueError, TypeError):
                        pass
            if init_events:
                init_events.sort(key=lambda e: e[0])
                in_prog = 0
                done = 0
                for ts, kind in init_events:
                    if kind == 'start':
                        in_prog += 1
                    else:
                        in_prog = max(0, in_prog - 1)
                        done += 1
                    partition_init_progress_times.append(ts)
                    partition_init_progress_in_progress.append(in_prog)
                    partition_init_progress_completed.append(done)
                logger.info(f"Built partition init progress time series with {len(init_events)} events")

        mongosync_sent_response_body = None
        for response in mongosync_sent_response:
            try:  
                parsed_body = json.loads(response['body'])
                # Only use this response if it contains 'progress'
                if 'progress' in parsed_body:
                    mongosync_sent_response_body = parsed_body  
            except (json.JSONDecodeError, TypeError):  
                mongosync_sent_response_body = None  # If parse fails, use None 
                logger.warning(f"No message 'sent response' found in the logs") 

        # Create a string with all the version information
        if version_info_list and isinstance(version_info_list[0], dict):  
            version = version_info_list[0].get('version', 'Unknown')  
            os_name = version_info_list[0].get('os', 'Unknown')  
            arch = version_info_list[0].get('arch', 'Unknown')  
            version_text = f"MongoSync Version: {version}, OS: {os_name}, Arch: {arch}"   
        else:  
            version_text = f"MongoSync Version is not available"  
            logger.error(version_text)  
            

        logger.info(f"Extracting data")

        # Log if options data is empty
        if not mongosync_hiddenflags:
            logger.info("mongosync_hiddenflags is empty")
        
        if not mongosync_opts_list:
            logger.info("mongosync_opts_list is empty")

        #Getting the Timezone
        try:  
            dt = parser.isoparse(data[0]['time'])  
            tz_name = dt.strftime('%Z')  
            tz_offset = dt.strftime('%z')  
            if tz_name:  
                timeZoneInfo = tz_name  
            elif tz_offset:  
                # Format offset as +HH:MM  
                tz_sign = tz_offset[0]  
                tz_hour = tz_offset[1:3]  
                tz_min = tz_offset[3:5]  
                timeZoneInfo = f"{tz_sign}{tz_hour}:{tz_min}"  
            else:  
                timeZoneInfo = ""  
        except Exception:  
            timeZoneInfo = ""  
                

        # Extract the data you want to plot
        times = [datetime.strptime(item['time'][:26], "%Y-%m-%dT%H:%M:%S.%f") for item in data if 'time' in item]
        totalEventsApplied = [item['totalEventsApplied'] for item in data if 'totalEventsApplied' in item]
        lagTimeSeconds = [item['lagTimeSeconds'] for item in data if 'lagTimeSeconds' in item]
        # Extract estimatedCopiedBytes time series from sent response entries
        # The 'body' field is a JSON string containing progress.collectionCopy.estimatedCopiedBytes
        estimatedCopiedBytes_series = []
        estimatedCopiedBytes_times = []
        for response in mongosync_sent_response:
            try:
                parsed_body = json.loads(response.get('body', '{}'))
                copied = (parsed_body.get('progress') or {}).get('collectionCopy') or {}
                copied = copied.get('estimatedCopiedBytes')
                if copied is not None and 'time' in response:
                    estimatedCopiedBytes_series.append(copied)
                    estimatedCopiedBytes_times.append(datetime.strptime(response['time'][:26], "%Y-%m-%dT%H:%M:%S.%f"))
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                continue
        CollectionCopySourceRead = [float(item['CollectionCopySourceRead']['averageDurationMs']) for item in mongosync_ops_stats if 'CollectionCopySourceRead' in item and 'averageDurationMs' in item['CollectionCopySourceRead']]
        CollectionCopySourceRead_maximum = [float(item['CollectionCopySourceRead']['maximumDurationMs']) for item in mongosync_ops_stats if 'CollectionCopySourceRead' in item and 'maximumDurationMs' in item['CollectionCopySourceRead']]
        CollectionCopySourceRead_numOperations = [float(item['CollectionCopySourceRead']['numOperations']) for item in mongosync_ops_stats if 'CollectionCopySourceRead' in item and 'numOperations' in item['CollectionCopySourceRead']]        
        CollectionCopyDestinationWrite = [float(item['CollectionCopyDestinationWrite']['averageDurationMs']) for item in mongosync_ops_stats if 'CollectionCopyDestinationWrite' in item and 'averageDurationMs' in item['CollectionCopyDestinationWrite']]
        CollectionCopyDestinationWrite_maximum  = [float(item['CollectionCopyDestinationWrite']['maximumDurationMs']) for item in mongosync_ops_stats if 'CollectionCopyDestinationWrite' in item and 'maximumDurationMs' in item['CollectionCopyDestinationWrite']]
        CollectionCopyDestinationWrite_numOperations = [float(item['CollectionCopyDestinationWrite']['numOperations']) for item in mongosync_ops_stats if 'CollectionCopyDestinationWrite' in item and 'numOperations' in item['CollectionCopyDestinationWrite']]
        CEASourceRead = [float(item['CEASourceRead']['averageDurationMs']) for item in mongosync_ops_stats if 'CEASourceRead' in item and 'averageDurationMs' in item['CEASourceRead']]
        CEASourceRead_maximum  = [float(item['CEASourceRead']['maximumDurationMs']) for item in mongosync_ops_stats if 'CEASourceRead' in item and 'maximumDurationMs' in item['CEASourceRead']]
        CEASourceRead_numOperations = [float(item['CEASourceRead']['numOperations']) for item in mongosync_ops_stats if 'CEASourceRead' in item and 'numOperations' in item['CEASourceRead']]
        CEADestinationWrite = [float(item['CEADestinationWrite']['averageDurationMs']) for item in mongosync_ops_stats if 'CEADestinationWrite' in item and 'averageDurationMs' in item['CEADestinationWrite']]
        CEADestinationWrite_maximum = [float(item['CEADestinationWrite']['maximumDurationMs']) for item in mongosync_ops_stats if 'CEADestinationWrite' in item and 'maximumDurationMs' in item['CEADestinationWrite']]    
        CEADestinationWrite_numOperations = [float(item['CEADestinationWrite']['numOperations']) for item in mongosync_ops_stats if 'CEADestinationWrite' in item and 'numOperations' in item['CEADestinationWrite']] 
        
        # Ping latency data (from operation stats)
        # Note: ping latency values can be non-numeric (e.g. 'unreachable'), so we filter those out safely
        def _safe_float(val):
            """Safely convert a value to float, returning None for non-numeric strings like 'unreachable'."""
            try:
                return float(val)
            except (ValueError, TypeError):
                return None
        sourcePingLatencyMs = [v for v in (_safe_float(item['sourcePingLatencyMs']) for item in mongosync_ops_stats if 'sourcePingLatencyMs' in item) if v is not None]
        destinationPingLatencyMs = [v for v in (_safe_float(item['destinationPingLatencyMs']) for item in mongosync_ops_stats if 'destinationPingLatencyMs' in item) if v is not None]
        
        # CRUD events rate data
        srcCRUDEventsPerSec = [float(item['srcCRUDEventsPerSec']) for item in mongosync_crud_rate if 'srcCRUDEventsPerSec' in item]
        crud_rate_times = [datetime.strptime(item['time'][:26], "%Y-%m-%dT%H:%M:%S.%f") for item in mongosync_crud_rate if 'time' in item]
        
        # Extract partition copy progress data
        partition_times = []
        partitions_copied = []
        partitions_total = []
        partition_re = re.compile(r"Completed writing (\d+) / (\d+) partitions")
        for item in mongosync_partition_progress:
            m = partition_re.search(item.get('message', ''))
            if m and 'time' in item:
                partition_times.append(datetime.strptime(item['time'][:26], "%Y-%m-%dT%H:%M:%S.%f"))
                copied = int(m.group(1))
                total = int(m.group(2))
                partitions_copied.append(copied)
                partitions_total.append(total)
        
        # Extract index building progress data from sent response entries
        index_built_times = []
        indexes_built = []
        indexes_total = []
        for response in mongosync_sent_response:
            try:
                parsed_body = json.loads(response.get('body', '{}'))
                idx_building = (parsed_body.get('progress') or {}).get('indexBuilding') or {}
                built = idx_building.get('indexesBuilt')
                total = idx_building.get('totalIndexesToBuild')
                if built is not None and total is not None and 'time' in response:
                    index_built_times.append(datetime.strptime(response['time'][:26], "%Y-%m-%dT%H:%M:%S.%f"))
                    indexes_built.append(built)
                    indexes_total.append(total)
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                continue

        # Estimated Source Oplog Time Remaining (from replication progress logs)
        def _parse_oplog_time_remaining_minutes(value):
            """Convert estimatedOplogTimeRemaining string to minutes."""
            if not value or value == "not yet checked":
                return None
            if value == "more than 72 hours":
                return 72 * 60
            if value == "less than 15 minutes":
                return 15
            m = re.match(r"(\d+)\s+minutes?", value)
            if m:
                return int(m.group(1))
            m = re.match(r"(\d+)\s+hours?", value)
            if m:
                return int(m.group(1)) * 60
            return None

        oplog_remaining_times = []
        oplog_remaining_minutes = []
        for item in data:
            val = _parse_oplog_time_remaining_minutes(item.get('estimatedOplogTimeRemaining'))
            if val is not None and 'time' in item:
                oplog_remaining_times.append(datetime.strptime(item['time'][:26], "%Y-%m-%dT%H:%M:%S.%f"))
                oplog_remaining_minutes.append(val)

        # Event Application Rate per Second (from replication progress logs)
        eventRatePerSecond = []
        eventRatePerSecond_times = []
        for item in data:
            rate = item.get('eventApplicationRatePerSecond')
            if rate is not None and 'time' in item:
                eventRatePerSecond.append(float(rate))
                eventRatePerSecond_times.append(datetime.strptime(item['time'][:26], "%Y-%m-%dT%H:%M:%S.%f"))

        dst_lag_times = [datetime.strptime(item['time'][:26], "%Y-%m-%dT%H:%M:%S.%f") for item in verifier_dst_lag_items if 'time' in item]
        verifierDstLagTimeSeconds = [item['verifierDstLagTimeSeconds'] for item in verifier_dst_lag_items if 'verifierDstLagTimeSeconds' in item]

        src_lag_times = [datetime.strptime(item['time'][:26], "%Y-%m-%dT%H:%M:%S.%f") for item in verifier_src_lag_items if 'time' in item]
        verifierSrcLagTimeSeconds = [item['verifierSrcLagTimeSeconds'] for item in verifier_src_lag_items if 'verifierSrcLagTimeSeconds' in item]

        # Calculate global date range from all time sources for X-axis synchronization
        all_times = []
        if times:
            all_times.extend(times)
        if crud_rate_times:
            all_times.extend(crud_rate_times)
        if partition_times:
            all_times.extend(partition_times)
        if estimatedCopiedBytes_times:
            all_times.extend(estimatedCopiedBytes_times)
        if index_built_times:
            all_times.extend(index_built_times)
        if dst_lag_times:
            all_times.extend(dst_lag_times)
        if src_lag_times:
            all_times.extend(src_lag_times)
        
        if all_times:
            global_min_date = min(all_times)
            global_max_date = max(all_times)
        else:
            global_min_date = None
            global_max_date = None
        
        # Initialize estimated_total_bytes and estimated_copied_bytes with a default value
        estimated_total_bytes = 0
        estimated_copied_bytes = 0
        
        phase_transitions = ""
        # Check that mongosync_sent_response_body is a dict before searching for 'progress'  
        if isinstance(mongosync_sent_response_body, dict):
            if 'progress' in mongosync_sent_response_body:
                estimated_total_bytes = mongosync_sent_response_body['progress']['collectionCopy']['estimatedTotalBytes']
                estimated_copied_bytes = mongosync_sent_response_body['progress']['collectionCopy']['estimatedCopiedBytes']

                try:  
                    # Try get Phase Transitions from the sent response body if it is Live Migrate
                    phase_transitions = mongosync_sent_response_body['progress']['atlasLiveMigrateMetrics']['PhaseTransitions']  
                except KeyError as e:  
                    logger.error(f"Key not found: {e}")  
                    phase_transitions = []

            else:
                logger.warning(f"Key 'progress' not found in mongosync_sent_response_body")

        # If phase_transitions is not empty, plot the phase transitions as it is Live Migrate
        if phase_transitions:
            phase_list = [item['Phase'] for item in phase_transitions]  
            ts_t_list = [item['Ts']['T'] for item in phase_transitions]  
            ts_t_list_formatted = [ 
                datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"  for t in ts_t_list 
            ]
        # Else get the phase transitions from the phase_transitions_json based on mongosync standalone 
        elif phase_transitions_json:
            phase_transitions = phase_transitions_json
            
            phase_list = [item.get('message') for item in phase_transitions]  
            ts_t_list = [item['time'] for item in phase_transitions]  
            # Strip timezone and preserve local time, consistent with other timestamp parsing (line 327)
            ts_t_list_formatted = [t[:26] for t in ts_t_list]

        # Include phase transition times in global date range
        if phase_transitions and ts_t_list_formatted:

            phase_datetimes = [datetime.strptime(t.rstrip('Z'), "%Y-%m-%dT%H:%M:%S.%f") for t in ts_t_list_formatted]
            all_times.extend(phase_datetimes)
            # Recompute global min/max with phase times included
            global_min_date = min(all_times)
            global_max_date = max(all_times)

        estimated_total_bytes, estimated_total_bytes_unit = format_byte_size(estimated_total_bytes)
        estimated_copied_bytes = convert_bytes(estimated_copied_bytes, estimated_total_bytes_unit)
        estimatedCopiedBytes_converted = [convert_bytes(b, estimated_total_bytes_unit) for b in estimatedCopiedBytes_series]

        logger.info(f"Plotting")

        # Create a subplot for the scatter plots (tables are now in a separate tab)
        fig = make_subplots(rows=13, cols=2, subplot_titles=("Mongosync Phases", "Mongosync Phases Table",
                                                            "Lag Time (seconds)", "Estimated Source Oplog Time Remaining (minutes)",
                                                            "Ping Latency (ms)", "Average Source CRUD Event Rate (Events/sec)",
                                                            "Partition Init Progress", "Partition Init Summary",
                                                            "Data Copied (" + estimated_total_bytes_unit + ")", "Estimated Total and Copied " + estimated_total_bytes_unit,
                                                            "Partitions Copied", "Total and Copied Partitions",
                                                            "Collection Copy - Avg and Max Read time (ms)", "Collection Copy Source Reads",
                                                            "Collection Copy - Avg and Max Write time (ms)", "Collection Copy Destination Writes",
                                                            "Change Events Applied", "Events Rate per Second",
                                                            "CEA Source - Avg and Max Read time (ms)", "CEA Source Reads",
                                                            "CEA Destination - Avg and Max Write time (ms)", "CEA Destination Writes",
                                                            "Index Built", "Total and Index Built",
                                                            "Source Verifier Lag Time (seconds)", "Destination Verifier Lag Time (seconds)"),
                            specs=[ [{}, {"type": "table"}], #Row 1: Mongosync Phases and Phases Table
                                    [{}, {}], #Row 2: Lag Time and Estimated Source Oplog Time Remaining
                                    [{}, {}], #Row 3: Ping Latency and CRUD Event Rate
                                    [{}, {"type": "table"}], #Row 4: Partition Init Progress and Summary
                                    [{}, {}], #Row 5: Data Copied Over Time + Estimated Total and Copied
                                    [{}, {}], #Row 6: Partitions Copied and Completion %
                                    [{}, {}], #Row 7: Collection Copy Source
                                    [{}, {}], #Row 8: Collection Copy Destination
                                    [{}, {}], #Row 9: Change Events Applied and Events Rate per Second
                                    [{}, {}], #Row 10: CEA Source
                                    [{}, {}], #Row 11: CEA Destination
                                    [{}, {}], #Row 12: Index Built and Total and Index Built
                                    [{}, {}] ]) #Row 13: Verifier Lag

        # Add traces

        # Row 1: Mongosync Phases
        if phase_transitions:
            fig.add_trace(go.Scatter(x=ts_t_list_formatted, y=phase_list, mode='markers+text',marker=dict(color='green')), row=1, col=1)
            fig.update_yaxes(showticklabels=False, row=1, col=1)  
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Mongosync Phases',textfont=dict(size=30, color="black")), row=1, col=1)
            fig.update_yaxes(range=[-1, 1], row=1, col=1)
            fig.update_xaxes(range=[-1, 1], row=1, col=1)

        # Row 1: Mongosync Phases Table
        if phase_transitions:
            phase_table_data = sorted(zip(ts_t_list_formatted, phase_list), key=lambda x: x[0])
            table_dates = [row[0] for row in phase_table_data]
            table_phases = [row[1] for row in phase_table_data]
            fig.add_trace(go.Table(
                header=dict(values=["Date Time", "Phase Name"]),
                cells=dict(values=[table_dates, table_phases])
            ), row=1, col=2)
        else:
            fig.add_trace(go.Table(
                header=dict(values=["Date Time", "Phase Name"]),
                cells=dict(values=[[], []])
            ), row=1, col=2)

        # Row 2: Lag Time
        if lagTimeSeconds:
            fig.add_trace(go.Scattergl(x=times, y=lagTimeSeconds, mode='lines', name='Seconds', legendgroup="groupEventsAndLags"), row=2, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Lag Time',textfont=dict(size=30, color="black")), row=2, col=1)
            fig.update_yaxes(range=[-1, 1], row=2, col=1)
            fig.update_xaxes(range=[-1, 1], row=2, col=1)

        # Row 2: Estimated Source Oplog Time Remaining (minutes)
        if oplog_remaining_minutes:
            fig.add_trace(go.Scattergl(x=oplog_remaining_times, y=oplog_remaining_minutes, mode='lines', name='Minutes Remaining', legendgroup="groupEventsAndLags"), row=2, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Oplog Time Remaining',textfont=dict(size=30, color="black")), row=2, col=2)
            fig.update_yaxes(range=[-1, 1], row=2, col=2)
            fig.update_xaxes(range=[-1, 1], row=2, col=2)

        # Row 3: Ping Latency
        if sourcePingLatencyMs or destinationPingLatencyMs:
            fig.add_trace(go.Scattergl(x=times, y=sourcePingLatencyMs, mode='lines', name='Source Ping (ms)', legendgroup="groupPingLatency"), row=3, col=1)
            fig.add_trace(go.Scattergl(x=times, y=destinationPingLatencyMs, mode='lines', name='Destination Ping (ms)', legendgroup="groupPingLatency"), row=3, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Ping Latency', textfont=dict(size=30, color="black")), row=3, col=1)
            fig.update_yaxes(range=[-1, 1], row=3, col=1)
            fig.update_xaxes(range=[-1, 1], row=3, col=1)

        # Row 3: Average Source CRUD Event Rate
        if srcCRUDEventsPerSec:
            fig.add_trace(go.Scattergl(x=crud_rate_times, y=srcCRUDEventsPerSec, mode='lines', name='Events/sec', legendgroup="groupCRUDRate"), row=3, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='CRUD Event Rate', textfont=dict(size=30, color="black")), row=3, col=2)
            fig.update_yaxes(range=[-1, 1], row=3, col=2)
            fig.update_xaxes(range=[-1, 1], row=3, col=2)

        # Row 4: Partition Init Progress - collections initializing vs completed over time
        if partition_init_progress_times:
            total_collections = len(partition_init_data) if partition_init_data else 0
            fig.add_trace(go.Scattergl(
                x=partition_init_progress_times, y=partition_init_progress_in_progress,
                mode='lines', name='In Progress', line=dict(color='#2196F3'),
                legendgroup="groupPartitionInitProgress"
            ), row=4, col=1)
            fig.add_trace(go.Scattergl(
                x=partition_init_progress_times, y=partition_init_progress_completed,
                mode='lines', name='Completed', line=dict(color='#4CAF50'),
                legendgroup="groupPartitionInitProgress"
            ), row=4, col=1)
            if total_collections > 0:
                fig.add_trace(go.Scattergl(
                    x=[partition_init_progress_times[0], partition_init_progress_times[-1]],
                    y=[total_collections, total_collections],
                    mode='lines', name='Total Collections', line=dict(color='gray', dash='dash'),
                    legendgroup="groupPartitionInitProgress"
                ), row=4, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Partition Init Progress', textfont=dict(size=30, color="black")), row=4, col=1)
            fig.update_yaxes(range=[-1, 1], row=4, col=1)
            fig.update_xaxes(range=[-1, 1], row=4, col=1)

        # Row 4: Partition Init Summary Table
        if partition_init_data:
            fig.add_trace(go.Table(
                header=dict(values=["Collection", "Type", "Partitions", "Doc Count", "Duration (s)"]),
                cells=dict(values=[
                    [d['collection'] for d in partition_init_data],
                    [d['type'] for d in partition_init_data],
                    [d['partition_count'] for d in partition_init_data],
                    [f"{d['doc_count']:,}" if d['doc_count'] else 'N/A' for d in partition_init_data],
                    [d['duration_sec'] if d['duration_sec'] is not None else 'N/A' for d in partition_init_data],
                ])
            ), row=4, col=2)
        else:
            fig.add_trace(go.Table(
                header=dict(values=["Collection", "Type", "Partitions", "Doc Count", "Duration (s)"]),
                cells=dict(values=[[], [], [], [], []])
            ), row=4, col=2)

        # Row 5: Data Copied Over Time
        if estimatedCopiedBytes_converted:
            fig.add_trace(go.Scattergl(x=estimatedCopiedBytes_times, y=estimatedCopiedBytes_converted, mode='lines', name='Copied ' + estimated_total_bytes_unit, legendgroup="groupTotalCopied"), row=5, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Data Copied Over Time',textfont=dict(size=30, color="black")), row=5, col=1)
            fig.update_yaxes(range=[-1, 1], row=5, col=1)
            fig.update_xaxes(range=[-1, 1], row=5, col=1)

        # Row 5: Estimated Total and Copied
        if estimated_total_bytes > 0 or estimated_copied_bytes > 0:
            fig.add_trace( go.Bar( name='Estimated ' + estimated_total_bytes_unit + ' to be Copied',  x=[estimated_total_bytes_unit],  y=[estimated_total_bytes], legendgroup="groupTotalCopied" ), row=5, col=2)
            fig.add_trace( go.Bar( name='Estimated Copied ' + estimated_total_bytes_unit, x=[estimated_total_bytes_unit],  y=[estimated_copied_bytes], legendgroup="groupTotalCopied"), row=5, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Estimated Total and Copied',textfont=dict(size=30, color="black")), row=5, col=2)
            fig.update_yaxes(range=[-1, 1], row=5, col=2)
            fig.update_xaxes(range=[-1, 1], row=5, col=2)

        # Row 6: Partitions Copied Over Time
        if partition_times:
            fig.add_trace(go.Scattergl(x=partition_times, y=partitions_copied, mode='lines', name='Partitions Copied', legendgroup="groupPartitions"), row=6, col=1)
            fig.add_trace(go.Scattergl(x=partition_times, y=partitions_total, mode='lines', name='Total Partitions', legendgroup="groupPartitions"), row=6, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Partitions Copied', textfont=dict(size=30, color="black")), row=6, col=1)
            fig.update_yaxes(range=[-1, 1], row=6, col=1)
            fig.update_xaxes(range=[-1, 1], row=6, col=1)

        # Row 6: Total and Copied Partitions
        if partition_times:
            last_copied = partitions_copied[-1]
            last_total = partitions_total[-1]
            fig.add_trace(go.Bar(name='Total Partitions', x=['Partitions'], y=[last_total], legendgroup="groupPartitions"), row=6, col=2)
            fig.add_trace(go.Bar(name='Copied Partitions', x=['Partitions'], y=[last_copied], legendgroup="groupPartitions"), row=6, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Total and Copied Partitions', textfont=dict(size=30, color="black")), row=6, col=2)
            fig.update_yaxes(range=[-1, 1], row=6, col=2)
            fig.update_xaxes(range=[-1, 1], row=6, col=2)

        # Row 7: Collection Copy Source Read
        if CollectionCopySourceRead or CollectionCopySourceRead_maximum:
            fig.add_trace(go.Scattergl(x=times, y=CollectionCopySourceRead, mode='lines', name='Average time (ms)', legendgroup="groupCCSourceRead"), row=7, col=1)
            fig.add_trace(go.Scattergl(x=times, y=CollectionCopySourceRead_maximum, mode='lines', name='Maximum time (ms)', legendgroup="groupCCSourceRead"), row=7, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Collection Copy Source Read',textfont=dict(size=30, color="black")), row=7, col=1)
            fig.update_yaxes(range=[-1, 1], row=7, col=1)
            fig.update_xaxes(range=[-1, 1], row=7, col=1)

        # Row 7: Collection Copy Source Reads (numOperations)
        if CollectionCopySourceRead_numOperations:
            fig.add_trace(go.Scattergl(x=times, y=CollectionCopySourceRead_numOperations, mode='lines', name='Reads', legendgroup="groupCCSourceRead"), row=7, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Collection Copy Source Reads',textfont=dict(size=30, color="black")), row=7, col=2)
            fig.update_yaxes(range=[-1, 1], row=7, col=2)
            fig.update_xaxes(range=[-1, 1], row=7, col=2)

        # Row 8: Collection Copy Destination Write
        if CollectionCopyDestinationWrite or CollectionCopyDestinationWrite_maximum:
            fig.add_trace(go.Scattergl(x=times, y=CollectionCopyDestinationWrite, mode='lines', name='Average time (ms)', legendgroup="groupCCDestinationWrite"), row=8, col=1)
            fig.add_trace(go.Scattergl(x=times, y=CollectionCopyDestinationWrite_maximum, mode='lines', name='Maximum time (ms)', legendgroup="groupCCDestinationWrite"), row=8, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Collection Copy Destination Write',textfont=dict(size=30, color="black")), row=8, col=1)
            fig.update_yaxes(range=[-1, 1], row=8, col=1)
            fig.update_xaxes(range=[-1, 1], row=8, col=1)

        # Row 8: Collection Copy Destination Writes (numOperations)
        if CollectionCopyDestinationWrite_numOperations:
            fig.add_trace(go.Scattergl(x=times, y=CollectionCopyDestinationWrite_numOperations, mode='lines', name='Writes', legendgroup="groupCCDestinationWrite"), row=8, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Collection Copy Destination Writes',textfont=dict(size=30, color="black")), row=8, col=2)
            fig.update_yaxes(range=[-1, 1], row=8, col=2)
            fig.update_xaxes(range=[-1, 1], row=8, col=2)

        # Row 9: Total Events Applied
        if totalEventsApplied:
            fig.add_trace(go.Scattergl(x=times, y=totalEventsApplied, mode='lines', name='Events', legendgroup="groupEventsAndLags"), row=9, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Change Events Applied',textfont=dict(size=30, color="black")), row=9, col=1)
            fig.update_yaxes(range=[-1, 1], row=9, col=1)
            fig.update_xaxes(range=[-1, 1], row=9, col=1)

        # Row 9: Events Rate per Second
        if eventRatePerSecond:
            fig.add_trace(go.Scattergl(x=eventRatePerSecond_times, y=eventRatePerSecond, mode='lines', name='Events/sec', legendgroup="groupEventsAndLags"), row=9, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Events Rate per Second',textfont=dict(size=30, color="black")), row=9, col=2)
            fig.update_yaxes(range=[-1, 1], row=9, col=2)
            fig.update_xaxes(range=[-1, 1], row=9, col=2)

        # Row 10: CEA Source Read
        if CEASourceRead or CEASourceRead_maximum:
            fig.add_trace(go.Scattergl(x=times, y=CEASourceRead, mode='lines', name='Average time (ms)', legendgroup="groupCEASourceRead"), row=10, col=1)
            fig.add_trace(go.Scattergl(x=times, y=CEASourceRead_maximum, mode='lines', name='Maximum time (ms)', legendgroup="groupCEASourceRead"), row=10, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='CEA Source Read',textfont=dict(size=30, color="black")), row=10, col=1)
            fig.update_yaxes(range=[-1, 1], row=10, col=1)
            fig.update_xaxes(range=[-1, 1], row=10, col=1)

        # Row 10: CEA Source Reads (numOperations)
        if CEASourceRead_numOperations:
            fig.add_trace(go.Scattergl(x=times, y=CEASourceRead_numOperations, mode='lines', name='Reads', legendgroup="groupCEASourceRead"), row=10, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='CEA Source Reads',textfont=dict(size=30, color="black")), row=10, col=2)
            fig.update_yaxes(range=[-1, 1], row=10, col=2)
            fig.update_xaxes(range=[-1, 1], row=10, col=2)

        # Row 11: CEA Destination Write
        if CEADestinationWrite or CEADestinationWrite_maximum:
            fig.add_trace(go.Scattergl(x=times, y=CEADestinationWrite, mode='lines', name='Average time (ms)', legendgroup="groupCEADestinationWrite"), row=11, col=1)
            fig.add_trace(go.Scattergl(x=times, y=CEADestinationWrite_maximum, mode='lines', name='Maximum time (ms)', legendgroup="groupCEADestinationWrite"), row=11, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='CEA Destination Write',textfont=dict(size=30, color="black")), row=11, col=1)
            fig.update_yaxes(range=[-1, 1], row=11, col=1)
            fig.update_xaxes(range=[-1, 1], row=11, col=1)

        # Row 11: CEA Destination Writes (numOperations)
        if CEADestinationWrite_numOperations:
            fig.add_trace(go.Scattergl(x=times, y=CEADestinationWrite_numOperations, mode='lines', name='Writes during CEA', legendgroup="groupCEADestinationWrite"), row=11, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='CEA Destination Writes',textfont=dict(size=30, color="black")), row=11, col=2)
            fig.update_yaxes(range=[-1, 1], row=11, col=2)
            fig.update_xaxes(range=[-1, 1], row=11, col=2)

        # Row 12: Index Built Over Time
        if index_built_times:
            fig.add_trace(go.Scattergl(x=index_built_times, y=indexes_built, mode='lines', name='Indexes Built', legendgroup="groupIndexBuilt"), row=12, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Index Built', textfont=dict(size=30, color="black")), row=12, col=1)
            fig.update_yaxes(range=[-1, 1], row=12, col=1)
            fig.update_xaxes(range=[-1, 1], row=12, col=1)

        # Row 12: Total and Index Built
        if index_built_times:
            last_built = indexes_built[-1]
            last_total = indexes_total[-1]
            fig.add_trace(go.Bar(name='Total Indexes', x=['Indexes'], y=[last_total], legendgroup="groupIndexBuilt"), row=12, col=2)
            fig.add_trace(go.Bar(name='Indexes Built', x=['Indexes'], y=[last_built], legendgroup="groupIndexBuilt"), row=12, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Total and Index Built', textfont=dict(size=30, color="black")), row=12, col=2)
            fig.update_yaxes(range=[-1, 1], row=12, col=2)
            fig.update_xaxes(range=[-1, 1], row=12, col=2)

        # Row 13: Source Verifier Lag Time
        if verifierSrcLagTimeSeconds:
            fig.add_trace(go.Scattergl(x=src_lag_times, y=verifierSrcLagTimeSeconds, mode='lines', name='Source Verifier Lag Time (seconds)', legendgroup="groupVerifierLag"), row=13, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Source Verifier Lag Time', textfont=dict(size=30, color="black")), row=13, col=1)
            fig.update_yaxes(range=[-1, 1], row=13, col=1)
            fig.update_xaxes(range=[-1, 1], row=13, col=1)

        # Row 13: Destination Verifier Lag Time
        if verifierDstLagTimeSeconds:
            fig.add_trace(go.Scattergl(x=dst_lag_times, y=verifierDstLagTimeSeconds, mode='lines', name='Destination Verifier Lag Time (seconds)', legendgroup="groupVerifierLag"), row=13, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Destination Verifier Lag Time', textfont=dict(size=30, color="black")), row=13, col=2)
            fig.update_yaxes(range=[-1, 1], row=13, col=2)
            fig.update_xaxes(range=[-1, 1], row=13, col=2)

        # Update layout
        # 225 per plot (13 rows = 2925)
        fig.update_layout(height=2925, width=1450, title_text="Mongosync Replication Progress - " + version_text + " - Timezone info: " + timeZoneInfo, legend_tracegroupgap=190, showlegend=False)
        
        # Force all y-axes to start at 0 for better visual comparison
        fig.update_yaxes(rangemode='tozero')
        
        # Add section label annotations above each section group
        section_labels = [
            ("Global Migration Metrics", 'yaxis'),        # row 1
            ("Collection Copy Metrics", 'yaxis6'),        # row 4
            ("CEA Metrics", 'yaxis15'),                   # row 9
            ("Indexes Metrics", 'yaxis21'),               # row 12
            ("Verifier Metrics", 'yaxis23'),               # row 13
        ]
        for section_name, yaxis_key in section_labels:
            domain = fig.layout[yaxis_key].domain
            if domain:
                y_pos = domain[1] + 0.012
                fig.add_annotation(
                    x=0.5, y=y_pos, xref='paper', yref='paper',
                    text=f'<b>{section_name}</b>',
                    showarrow=False,
                    font=dict(size=11, color='#1A3C4A'),
                    bgcolor='rgba(1, 107, 248, 0.12)',
                    bordercolor='#016BF8',
                    borderwidth=1,
                    borderpad=4
                )
        
        # Synchronize X-axis date range across all date-based plots
        # Tables at row 1 col 2 and row 4 col 2 are excluded (no date axis)
        if global_min_date and global_max_date:
            fig.update_xaxes(range=[global_min_date, global_max_date], row=1, col=1)
            for row in range(2, 4):  # rows 2-3 (both cols are charts)
                for col in range(1, 3):
                    fig.update_xaxes(range=[global_min_date, global_max_date], row=row, col=col)
            fig.update_xaxes(range=[global_min_date, global_max_date], row=4, col=1)
            for row in range(5, 14):  # rows 5-13 (both cols are charts)
                for col in range(1, 3):
                    fig.update_xaxes(range=[global_min_date, global_max_date], row=row, col=col)

        fig.update_layout(
            legend=dict(
                y=1
            )
        )

        # Convert the figure to JSON
        plot_json = json.dumps(fig, cls=PlotlyJSONEncoder) if logs_line_count > 0 else ""

        logger.info(f"Render the plot in the browser")
        
        # Generate metrics plot if we have metrics data
        metrics_plot_json = ""
        if metrics_collector.metrics_count > 0:
            logger.info(f"Creating Prometheus metrics plots")
            metrics_plot_json = create_metrics_plots(metrics_collector)

        # Prepare mongosync options data for HTML table
        options_data = []
        if mongosync_opts_list:
            for key, value in mongosync_opts_list[0].items():
                # Convert complex values to string representation
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, indent=2)
                options_data.append({'key': str(key), 'value': str(value)})
        
        # Prepare hidden options data for HTML table
        hidden_options_data = []
        if mongosync_hiddenflags:
            for key, value in mongosync_hiddenflags[0].items():
                # Convert complex values to string representation
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, indent=2)
                hidden_options_data.append({'key': str(key), 'value': str(value)})

        # Prepare start options data for HTML table
        start_options_data = []
        if mongosync_start_options:
            for key, value in mongosync_start_options[0].items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, indent=2)
                start_options_data.append({'key': str(key), 'value': str(value)})

        # Deduplicate natural order collections
        natural_order_data = []
        seen_nat = set()
        for item in natural_order_collections:
            key = (item['database'], item['collection'])
            if key not in seen_nat:
                seen_nat.add(key)
                natural_order_data.append(item)

        # Determine which tabs have data
        has_logs_data = logs_line_count > 0 and len(data) > 0
        has_metrics_data = metrics_collector.metrics_count > 0

        template_data = {
            'plot_json': plot_json,
            'metrics_plot_json': metrics_plot_json,
            'options_data': options_data,
            'hidden_options_data': hidden_options_data,
            'start_options_data': start_options_data,
            'natural_order_data': natural_order_data,
            'errors_data': matched_errors,
            'partition_init_data': partition_init_data,
            'has_logs_data': has_logs_data,
            'has_metrics_data': has_metrics_data,
            'log_viewer_lines': list(raw_log_tail),
            'log_store_id': store_id,
        }

        snapshot_id = str(uuid_mod.uuid4())
        try:
            save_snapshot(snapshot_id, filename, file_size, line_count, store_id, template_data)
        except Exception as e:
            logger.warning(f"Failed to save snapshot: {e}")

        return render_template('upload_results.html', **template_data)
