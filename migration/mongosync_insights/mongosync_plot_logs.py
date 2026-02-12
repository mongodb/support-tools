import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from plotly.subplots import make_subplots
from tqdm import tqdm
from flask import request, render_template
import json
from datetime import datetime, timezone
from dateutil import parser
import re
import logging
import os
import magic
from werkzeug.utils import secure_filename
from mongosync_plot_utils import format_byte_size, convert_bytes
from app_config import MAX_FILE_SIZE, ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES, load_error_patterns, classify_file_type
from file_decompressor import decompress_file, decompress_file_classified, is_compressed_mime_type
from mongosync_plot_prometheus_metrics import MetricsCollector, create_metrics_plots

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
        
        # Check MIME type using python-magic
        try:
            mime = magic.Magic(mime=True)
            file.seek(0)
            # Read first 2KB for MIME detection (sufficient for most file types)
            file_sample = file.read(2048)
            file_mime_type = mime.from_buffer(file_sample)
            file.seek(0)  # Reset to beginning
            
            logger.info(f"Detected MIME type: {file_mime_type}")
            
            if file_mime_type not in ALLOWED_MIME_TYPES:
                logger.error(f"Invalid MIME type: {file_mime_type}. Allowed: {ALLOWED_MIME_TYPES}")
                return render_template('error.html',
                                     error_title="Invalid File Type",
                                     error_message=f"File MIME type '{file_mime_type}' is not allowed. Only JSON/text files are accepted. Detected type: {file_mime_type}")
        except Exception as e:
            logger.error(f"Error detecting MIME type: {e}")
            return render_template('error.html',
                                 error_title="File Validation Error",
                                 error_message=f"Unable to validate file type: {str(e)}")
        
        logger.info(f"File validation passed: {filename} ({file_size} bytes, {file_ext}, MIME: {file_mime_type})")
        # Optimized single-pass log parsing with streaming approach
        logging.info("Starting optimized log parsing - single pass through file")
        
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
            'partition_copy_progress': re.compile(r"Completed writing \d+ / \d+ partitions to destination cluster", re.IGNORECASE)
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
        
        # Initialize metrics collector for prometheus metrics
        metrics_collector = MetricsCollector()
        
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
                # Unknown file type - skip
                continue
                
            try:
                # Parse JSON only once per line (for logs)
                json_obj = json.loads(line)
                message = json_obj.get('message', '')
                
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
                
                if patterns['crud_events_rate'].search(message):
                    mongosync_crud_rate.append(json_obj)
                
                if patterns['partition_copy_progress'].search(message):
                    mongosync_partition_progress.append(json_obj)
                
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
                    logging.warning(f"Invalid JSON on line {line_count}: {e}")
                # Only treat as fatal error if this is the first error AND we haven't processed any valid lines
                if invalid_json_count == 1 and logs_line_count == 0 and metrics_line_count == 0:
                    logging.error(f"File appears to contain invalid JSON. First error on line {line_count}: {e}")
                    return render_template('error.html',
                                         error_title="Invalid File Format",
                                         error_message=f"The uploaded file does not contain valid JSON format. Error on line {line_count}: {str(e)}. Please ensure you're uploading a valid mongosync log file in NDJSON format.")
        
        logging.info(f"Processed {line_count} total lines ({logs_line_count} logs, {metrics_line_count} metrics), found {invalid_json_count} invalid JSON lines")
        logging.info(f"Found: {len(data)} replication progress, {len(version_info_list)} version info, "
                    f"{len(mongosync_ops_stats)} operation stats, {len(mongosync_sent_response)} sent responses, "
                    f"{len(phase_transitions_json)} phase transitions, {len(mongosync_opts_list)} options, "
                    f"{len(mongosync_hiddenflags)} hidden flags, {len(mongosync_crud_rate)} CRUD rate entries, "
                    f"{len(mongosync_partition_progress)} partition progress entries, "
                    f"{len(matched_errors)} common errors")
        logging.info(f"Metrics collector: {metrics_collector.metrics_count} metric points from {metrics_collector.line_count} lines")  
        
        # Sort log data by timestamp to ensure correct chronological plot ordering
        # (archives may contain rotated log files in non-chronological order)
        data.sort(key=lambda x: x.get('time', ''))
        mongosync_ops_stats.sort(key=lambda x: x.get('time', ''))
        mongosync_crud_rate.sort(key=lambda x: x.get('time', ''))
        mongosync_partition_progress.sort(key=lambda x: x.get('time', ''))

        # The 'body' field is also a JSON string, so parse that as well
        #mongosync_sent_response_body = json.loads(mongosync_sent_response.get('body'))
        mongosync_sent_response_body = None 
        for response in mongosync_sent_response:
            try:  
                parsed_body = json.loads(response['body'])
                # Only use this response if it contains 'progress'
                if 'progress' in parsed_body:
                    mongosync_sent_response_body = parsed_body  
            except (json.JSONDecodeError, TypeError):  
                mongosync_sent_response_body = None  # If parse fails, use None 
                logging.warning(f"No message 'sent response' found in the logs") 

        # Create a string with all the version information
        if version_info_list and isinstance(version_info_list[0], dict):  
            version = version_info_list[0].get('version', 'Unknown')  
            os_name = version_info_list[0].get('os', 'Unknown')  
            arch = version_info_list[0].get('arch', 'Unknown')  
            version_text = f"MongoSync Version: {version}, OS: {os_name}, Arch: {arch}"   
        else:  
            version_text = f"MongoSync Version is not available"  
            logging.error(version_text)  
            

        logging.info(f"Extracting data")

        # Log if options data is empty
        if not mongosync_hiddenflags:
            logging.info("mongosync_hiddenflags is empty")
        
        if not mongosync_opts_list:
            logging.info("mongosync_opts_list is empty")

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
        sourcePingLatencyMs = [float(item['sourcePingLatencyMs']) for item in mongosync_ops_stats if 'sourcePingLatencyMs' in item]
        destinationPingLatencyMs = [float(item['destinationPingLatencyMs']) for item in mongosync_ops_stats if 'destinationPingLatencyMs' in item]
        
        # CRUD events rate data
        srcCRUDEventsPerSec = [float(item['srcCRUDEventsPerSec']) for item in mongosync_crud_rate if 'srcCRUDEventsPerSec' in item]
        crud_rate_times = [datetime.strptime(item['time'][:26], "%Y-%m-%dT%H:%M:%S.%f") for item in mongosync_crud_rate if 'time' in item]
        
        # Extract partition copy progress data
        partition_times = []
        partitions_copied = []
        partitions_total = []
        partitions_pct = []
        partition_re = re.compile(r"Completed writing (\d+) / (\d+) partitions")
        for item in mongosync_partition_progress:
            m = partition_re.search(item.get('message', ''))
            if m and 'time' in item:
                partition_times.append(datetime.strptime(item['time'][:26], "%Y-%m-%dT%H:%M:%S.%f"))
                copied = int(m.group(1))
                total = int(m.group(2))
                partitions_copied.append(copied)
                partitions_total.append(total)
                partitions_pct.append((copied / total * 100) if total > 0 else 0)
        
        # Calculate global date range from all time sources for X-axis synchronization
        all_times = []
        if times:
            all_times.extend(times)
        if crud_rate_times:
            all_times.extend(crud_rate_times)
        if partition_times:
            all_times.extend(partition_times)
        
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
        #if 'progress' in mongosync_sent_response_body:
            #getting the estimated total and copied
            if 'progress' in mongosync_sent_response_body:
                estimated_total_bytes = mongosync_sent_response_body['progress']['collectionCopy']['estimatedTotalBytes']
                estimated_copied_bytes = mongosync_sent_response_body['progress']['collectionCopy']['estimatedCopiedBytes']

                #Getting the Phase Transisitons
                try:  
                    # Try get Phase Transitions from the sent response body if it is Live Migrate
                    phase_transitions = mongosync_sent_response_body['progress']['atlasLiveMigrateMetrics']['PhaseTransitions']  
                except KeyError as e:  
                    logging.error(f"Key not found: {e}")  
                    phase_transitions = []

            else:
                logging.warning(f"Key 'progress' not found in mongosync_sent_response_body")
            
            # If phase_transitions is not empty, plot the phase transitions as it is Live Migrate
            if phase_transitions:
                phase_list = [item['Phase'] for item in phase_transitions]  
                ts_t_list = [item['Ts']['T'] for item in phase_transitions]  
                ts_t_list_formatted = [ 
                    datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"  for t in ts_t_list 
                ]
            # Else get the phase transitions from the phase_transitions_json based on mongosync standalone 
            else:
                if phase_transitions_json:
                    #print (phase_transitions_json)
                    phase_transitions = phase_transitions_json
                    
                    phase_list = [item.get('message') for item in phase_transitions]  
                    ts_t_list = [item['time'] for item in phase_transitions]  
                    # Replace 'Z' with '+00:00' for Python < 3.11 compatibility
                    ts_t_list_formatted = [  
                        datetime.fromisoformat(t.replace('Z', '+00:00')).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"  
                        for t in ts_t_list  
                    ]  
        else:
            logging.warning(f"Response body is empty")

        estimated_total_bytes, estimated_total_bytes_unit = format_byte_size(estimated_total_bytes)
        estimated_copied_bytes = convert_bytes(estimated_copied_bytes, estimated_total_bytes_unit)

        logging.info(f"Plotting")

        # Create a subplot for the scatter plots (tables are now in a separate tab)
        fig = make_subplots(rows=8, cols=2, subplot_titles=("Mongosync Phases", "Estimated Total and Copied " + estimated_total_bytes_unit,
                                                            "Partitions Copied Over Time", "Partition Completion %",
                                                            "Lag Time (seconds)", "Change Events Applied",
                                                            "Ping Latency (ms)", "Average Source CRUD Event Rate (Events/sec)",
                                                            "Collection Copy - Avg and Max Read time (ms)", "Collection Copy Source Reads",
                                                            "Collection Copy - Avg and Max Write time (ms)", "Collection Copy Destination Writes",
                                                            "CEA Source - Avg and Max Read time (ms)", "CEA Source Reads",
                                                            "CEA Destination - Avg and Max Write time (ms)", "CEA Destination Writes"),
                            specs=[ [{}, {}], #Mongosync Phases and Estimated Total and Copied 
                                    [{}, {}], #Partitions Copied and Completion %
                                    [{}, {}], #Lag Time and Events Applied
                                    [{}, {}], #Ping Latency and CRUD Event Rate
                                    [{}, {}], #Collection Copy Source
                                    [{}, {}], #Collection Copy Destination
                                    [{}, {}], #CEA Source
                                    [{}, {}] ]) #CEA Destination

        # Add traces

        # Mongosync Phases
        if phase_transitions:
            fig.add_trace(go.Scatter(x=ts_t_list_formatted, y=phase_list, mode='markers+text',marker=dict(color='green')), row=1, col=1)
            fig.update_yaxes(showticklabels=False, row=1, col=1)  
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Mongosync Phases',textfont=dict(size=30, color="black")), row=1, col=1)
            fig.update_yaxes(range=[-1, 1], row=1, col=1)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=1, col=1)  # Also center horizontally

        # Estimated Total and Copied
        if estimated_total_bytes > 0 or estimated_copied_bytes > 0:
        #fig = go.Figure(data=[go.Bar(name='Estimated Total Bytes', x=['Bytes'], y=[estimated_total_bytes], row=1, col=1), go.Bar(name='Estimated Copied Bytes', x=['Bytes'], y=[estimated_copied_bytes])], row=1, col=1)
            fig.add_trace( go.Bar( name='Estimated ' + estimated_total_bytes_unit + ' to be Copied',  x=[estimated_total_bytes_unit],  y=[estimated_total_bytes], legendgroup="groupTotalCopied" ), row=1, col=2)
            fig.add_trace( go.Bar( name='Estimated Copied ' + estimated_total_bytes_unit, x=[estimated_total_bytes_unit],  y=[estimated_copied_bytes], legendgroup="groupTotalCopied"), row=1, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Estimated Total and Copied',textfont=dict(size=30, color="black")), row=1, col=2)
            fig.update_yaxes(range=[-1, 1], row=1, col=2)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=1, col=2)  # Also center horizontally

        # Partitions Copied Over Time
        if partition_times:
            fig.add_trace(go.Scattergl(x=partition_times, y=partitions_copied, mode='lines', name='Partitions Copied', legendgroup="groupPartitions"), row=2, col=1)
            fig.add_trace(go.Scattergl(x=partition_times, y=partitions_total, mode='lines', name='Total Partitions', legendgroup="groupPartitions"), row=2, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Partitions Copied', textfont=dict(size=30, color="black")), row=2, col=1)
            fig.update_yaxes(range=[-1, 1], row=2, col=1)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=2, col=1)  # Also center horizontally

        # Partition Completion %
        if partition_times:
            fig.add_trace(go.Scattergl(x=partition_times, y=partitions_pct, mode='lines', name='Completion %', legendgroup="groupPartitions"), row=2, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Partition Completion %', textfont=dict(size=30, color="black")), row=2, col=2)
            fig.update_yaxes(range=[-1, 1], row=2, col=2)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=2, col=2)  # Also center horizontally

        # Lag Time
        if lagTimeSeconds:
            fig.add_trace(go.Scattergl(x=times, y=lagTimeSeconds, mode='lines', name='Seconds', legendgroup="groupEventsAndLags"), row=3, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Lag Time',textfont=dict(size=30, color="black")), row=3, col=1)
            fig.update_yaxes(range=[-1, 1], row=3, col=1)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=3, col=1)  # Also center horizontally
        #fig.update_yaxes(title_text="Lag Time (seconds)", row=3, col=1)

        # Total Events Applied
        if totalEventsApplied:
            fig.add_trace(go.Scattergl(x=times, y=totalEventsApplied, mode='lines', name='Events', legendgroup="groupEventsAndLags"), row=3, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Change Events Applied',textfont=dict(size=30, color="black")), row=3, col=2)
            fig.update_yaxes(range=[-1, 1], row=3, col=2)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=3, col=2)  # Also center horizontally
        #fig.update_yaxes(title_text="Change Events Applied", row=3, col=2)

        # Ping Latency
        if sourcePingLatencyMs or destinationPingLatencyMs:
            fig.add_trace(go.Scattergl(x=times, y=sourcePingLatencyMs, mode='lines', name='Source Ping (ms)', legendgroup="groupPingLatency"), row=4, col=1)
            fig.add_trace(go.Scattergl(x=times, y=destinationPingLatencyMs, mode='lines', name='Destination Ping (ms)', legendgroup="groupPingLatency"), row=4, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Ping Latency', textfont=dict(size=30, color="black")), row=4, col=1)
            fig.update_yaxes(range=[-1, 1], row=4, col=1)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=4, col=1)  # Also center horizontally

        # Average Source CRUD Event Rate
        if srcCRUDEventsPerSec:
            fig.add_trace(go.Scattergl(x=crud_rate_times, y=srcCRUDEventsPerSec, mode='lines', name='Events/sec', legendgroup="groupCRUDRate"), row=4, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='CRUD Event Rate', textfont=dict(size=30, color="black")), row=4, col=2)
            fig.update_yaxes(range=[-1, 1], row=4, col=2)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=4, col=2)  # Also center horizontally

        # Collection Copy Source Read
        if CollectionCopySourceRead or CollectionCopySourceRead_maximum:
            fig.add_trace(go.Scattergl(x=times, y=CollectionCopySourceRead, mode='lines', name='Average time (ms)', legendgroup="groupCCSourceRead"), row=5, col=1)
            fig.add_trace(go.Scattergl(x=times, y=CollectionCopySourceRead_maximum, mode='lines', name='Maximum time (ms)', legendgroup="groupCCSourceRead"), row=5, col=1)
            #fig.update_yaxes(title_text="Avg and Max time (ms)", secondary_y=False, row=5, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Collection Copy Source Read',textfont=dict(size=30, color="black")), row=5, col=1)
            fig.update_yaxes(range=[-1, 1], row=5, col=1)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=5, col=1)  # Also center horizontally

        if CollectionCopySourceRead_numOperations:
            fig.add_trace(go.Scattergl(x=times, y=CollectionCopySourceRead_numOperations, mode='lines', name='Reads', legendgroup="groupCCSourceRead"), row=5, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Collection Copy Source Reads',textfont=dict(size=30, color="black")), row=5, col=2)

            fig.update_yaxes(range=[-1, 1], row=5, col=2)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=5, col=2)  # Also center horizontally
        #fig.update_yaxes(title_text="Number of Reads", secondary_y=True, row=5, col=2)

        #Collection Copy Destination
        if CollectionCopyDestinationWrite or CollectionCopyDestinationWrite_maximum:
            fig.add_trace(go.Scattergl(x=times, y=CollectionCopyDestinationWrite, mode='lines', name='Average time (ms)', legendgroup="groupCCDestinationWrite"), row=6, col=1)
            fig.add_trace(go.Scattergl(x=times, y=CollectionCopyDestinationWrite_maximum, mode='lines', name='Maximum time (ms)', legendgroup="groupCCDestinationWrite"), row=6, col=1)
            #fig.update_yaxes(title_text="Avg and Max time (ms)", secondary_y=False, row=6, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Collection Copy Destination Write',textfont=dict(size=30, color="black")), row=6, col=1)
            fig.update_yaxes(range=[-1, 1], row=6, col=1)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=6, col=1)  # Also center horizontally

        if CollectionCopyDestinationWrite_numOperations:
            fig.add_trace(go.Scattergl(x=times, y=CollectionCopyDestinationWrite_numOperations, mode='lines', name='Writes', legendgroup="groupCCDestinationWrite"), row=6, col=2,)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Collection Copy Destination Writes',textfont=dict(size=30, color="black")), row=6, col=2)
            fig.update_yaxes(range=[-1, 1], row=6, col=2)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=6, col=2)  # Also center horizontally

        #CEA Source
        if CEASourceRead or CEASourceRead_maximum:
            fig.add_trace(go.Scattergl(x=times, y=CEASourceRead, mode='lines', name='Average time (ms)', legendgroup="groupCEASourceRead"), row=7, col=1)
            fig.add_trace(go.Scattergl(x=times, y=CEASourceRead_maximum, mode='lines', name='Maximum time (ms)', legendgroup="groupCEASourceRead"), row=7, col=1)
            #fig.update_yaxes(title_text="Avg and Max time (ms)", secondary_y=False, row=7, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='CEA Source Read',textfont=dict(size=30, color="black")), row=7, col=1)
            fig.update_yaxes(range=[-1, 1], row=7, col=1)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=7, col=1)  # Also center horizontally

        if CEASourceRead_numOperations:
            fig.add_trace(go.Scattergl(x=times, y=CEASourceRead_numOperations, mode='lines', name='Reads', legendgroup="groupCEASourceRead"), row=7, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='CEA Source Reads',textfont=dict(size=30, color="black")), row=7, col=2)
            fig.update_yaxes(range=[-1, 1], row=7, col=2)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=7, col=2)  # Also center horizontally

        #CEA Destination
        if CEADestinationWrite or CEADestinationWrite_maximum:
            fig.add_trace(go.Scattergl(x=times, y=CEADestinationWrite, mode='lines', name='Average time (ms)', legendgroup="groupCEADestinationWrite"), row=8, col=1)
            fig.add_trace(go.Scattergl(x=times, y=CEADestinationWrite_maximum, mode='lines', name='Maximum time (ms)', legendgroup="groupCEADestinationWrite"), row=8, col=1)
            #fig.update_yaxes(title_text="Avg and Max time (ms)", secondary_y=False, row=8, col=1)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='CEA Destination Write',textfont=dict(size=30, color="black")), row=8, col=1)
            fig.update_yaxes(range=[-1, 1], row=8, col=1)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=8, col=1)  # Also center horizontally

        if CEADestinationWrite_numOperations:
            fig.add_trace(go.Scattergl(x=times, y=CEADestinationWrite_numOperations, mode='lines', name='Writes during CEA', legendgroup="groupCEADestinationWrite"), row=8, col=2)
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='CEA Destination Writes',textfont=dict(size=30, color="black")), row=8, col=2)
            fig.update_yaxes(range=[-1, 1], row=8, col=2)  # Center the text vertically
            fig.update_xaxes(range=[-1, 1], row=8, col=2)  # Also center horizontally

        # Update layout
        # 225 per plot (8 rows = 1800)
        fig.update_layout(height=1800, width=1450, title_text="Mongosync Replication Progress - " + version_text + " - Timezone info: " + timeZoneInfo, legend_tracegroupgap=190, showlegend=False)
        
        # Force all y-axes to start at 0 for better visual comparison
        fig.update_yaxes(rangemode='tozero')
        
        # Synchronize X-axis date range across all date-based plots (rows 2-8)
        if global_min_date and global_max_date:
            for row in range(2, 9):  # rows 2 through 8
                for col in range(1, 3):  # columns 1 and 2
                    fig.update_xaxes(range=[global_min_date, global_max_date], row=row, col=col)

        fig.update_layout(
            legend=dict(
                y=1
            )
        )

        # Convert the figure to JSON
        plot_json = json.dumps(fig, cls=PlotlyJSONEncoder) if logs_line_count > 0 else ""

        logging.info(f"Render the plot in the browser")
        
        # Generate metrics plot if we have metrics data
        metrics_plot_json = ""
        if metrics_collector.metrics_count > 0:
            logging.info(f"Creating Prometheus metrics plots")
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

        # Determine which tabs have data
        has_logs_data = logs_line_count > 0 and len(data) > 0
        has_metrics_data = metrics_collector.metrics_count > 0

        # Render the plot in the browser
        return render_template('upload_results.html', 
                             plot_json=plot_json,
                             metrics_plot_json=metrics_plot_json,
                             options_data=options_data,
                             hidden_options_data=hidden_options_data,
                             errors_data=matched_errors,
                             has_logs_data=has_logs_data,
                             has_metrics_data=has_metrics_data)
