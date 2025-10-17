import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from plotly.subplots import make_subplots
from tqdm import tqdm
from flask import request, redirect, render_template, flash
import json
from datetime import datetime, timezone
from dateutil import parser
import re
import logging
import os
from werkzeug.utils import secure_filename
from mongosync_plot_utils import format_byte_size, convert_bytes
from app_config import MAX_FILE_SIZE, ALLOWED_EXTENSIONS

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
        
        logger.info(f"File validation passed: {filename} ({file_size} bytes, {file_ext})")
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
            'hidden_flags': re.compile(r"Mongosync HiddenFlags", re.IGNORECASE)
        }
        
        # Initialize result containers
        data = []
        version_info_list = []
        mongosync_ops_stats = []
        mongosync_sent_response = []
        phase_transitions_json = []
        mongosync_opts_list = []
        mongosync_hiddenflags = []
        
        # Single pass through the file with streaming
        line_count = 0
        invalid_json_count = 0
        
        # Reset file pointer to beginning
        file.seek(0)
        
        for line in tqdm(file, desc="Processing log file"):
            line_count += 1
            line = line.strip()
            
            if not line:  # Skip empty lines
                continue
                
            try:
                # Parse JSON only once per line
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
                    
            except json.JSONDecodeError as e:
                invalid_json_count += 1
                if invalid_json_count <= 5:  # Log first 5 errors to avoid spam
                    logging.warning(f"Invalid JSON on line {line_count}: {e}")
                if invalid_json_count == 1:  # If this is the first error, it might be a non-JSON file
                    logging.error(f"File appears to contain invalid JSON. First error on line {line_count}: {e}")
                    return redirect(request.url)
        
        logging.info(f"Processed {line_count} lines, found {invalid_json_count} invalid JSON lines")
        logging.info(f"Found: {len(data)} replication progress, {len(version_info_list)} version info, "
                    f"{len(mongosync_ops_stats)} operation stats, {len(mongosync_sent_response)} sent responses, "
                    f"{len(phase_transitions_json)} phase transitions, {len(mongosync_opts_list)} options, "
                    f"{len(mongosync_hiddenflags)} hidden flags")  
        

        # The 'body' field is also a JSON string, so parse that as well
        #mongosync_sent_response_body = json.loads(mongosync_sent_response.get('body'))
        mongosync_sent_response_body = None 
        for response in mongosync_sent_response:
            try:  
                mongosync_sent_response_body = json.loads(response['body'])  
            except (json.JSONDecodeError, TypeError):  
                mongosync_sent_response_body = None  # If parse fails, use None 
                logging.warning(f"No message 'sent response' found in the logs") 

        # Create a string with all the version information
        if version_info_list and isinstance(version_info_list[0], dict):  
            version = version_info_list[0].get('version', 'Unknown')  
            operating_system = version_info_list[0].get('os', 'Unknown')  
            arch = version_info_list[0].get('arch', 'Unknown')  
            version_text = f"MongoSync Version: {version}, OS: {operating_system}, Arch: {arch}"   
        else:  
            version_text = f"MongoSync Version is not available"  
            logging.error(version_text)  
            

        logging.info(f"Extracting data")

        # Extract the keys from the mongosync_hiddenflags
        # For each key, extract the corresponding values from mongosync_hiddenflags
        if mongosync_hiddenflags:
            keys = list(mongosync_hiddenflags[0].keys())
            #It takes the first hidden options listed
            values = [str(v) for v in mongosync_hiddenflags[0].values()]  
            #If wanted to taken all hidden options listed, replace with it
            #values = [[str(item[key]).replace('{', '').replace('}', '')  for item in mongosync_hiddenflags] for key in keys]

            # Create a table trace with the keys as the first column and the corresponding values as the second column
            table_hiddenflags = go.Table(
                header=dict(values=['Key', 'Value'], font=dict(size=12, color='black')),
                cells=dict(values=[keys, values],  align=['left'], font=dict(size=10, color='darkblue')), #
                columnwidth=[0.75, 2.5]  # Adjust the column widths as needed
            )
        else:
            logging.info("mongosync_hiddenflags is empty")
            table_hiddenflags = go.Table(
                header=dict(values=['Mongosync Hidden Flags']),
                cells=dict(values=[["No Mongosync Hidden Flags found in the log file"]])
            )
        
        if mongosync_opts_list:
            keys = list(mongosync_opts_list[0].keys())
            #It takes the first options listed
            values = list(mongosync_opts_list[0].values()) 
            #If wanted to taken all option listed, replace with it
            #values = [[item[key] for item in mongosync_opts_list[0]] for key in keys]

            # Create a table trace with the keys as the first column and the corresponding values as the second column
            table_trace = go.Table(
                header=dict(values=['Key', 'Value'], font=dict(size=12, color='black')),
                cells=dict(values=[keys, values], align=['left'], font=dict(size=10, color='darkblue')),
                columnwidth=[0.75, 2.5]  # Adjust the column widths as needed
            )

            # If the key is 'hiddenFlags', extract its keys and values and add them to the keys and values lists
            for i, key in enumerate(keys):
                if key == 'hiddenFlags':
                    hidden_keys = list(values[i][0].keys())
                    hidden_values = [[item.get(key, '') for item in values[i]] for key in hidden_keys]
                    keys = keys[:i] + hidden_keys + keys[i+1:]
                    values = values[:i] + hidden_values + values[i+1:]
        else:
            logging.info("mongosync_opts_list is empty")
            table_trace = go.Table(header=dict(values=['Mongosync Options']),
            cells=dict(values=[["No Mongosync Options found in the log file"]]))

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
        
        # Initialize estimated_total_bytes and estimated_copied_bytes with a default value
        estimated_total_bytes = 0
        estimated_copied_bytes = 0
        
        phase_transitions = ""
        # Check that mongosync_sent_response_body is a dict before searching for 'progress'  
        if isinstance(mongosync_sent_response_body, dict) and 'progress' in mongosync_sent_response_body:
        #if 'progress' in mongosync_sent_response_body:
            #getting the estimated total and copied
            estimated_total_bytes = mongosync_sent_response_body['progress']['collectionCopy']['estimatedTotalBytes']
            estimated_copied_bytes = mongosync_sent_response_body['progress']['collectionCopy']['estimatedCopiedBytes']
            
            #Getting the Phase Transisitons
            try:  
                # Try to access deeply nested key  
                phase_transitions = mongosync_sent_response_body['progress']['atlasLiveMigrateMetrics']['PhaseTransitions']  
            except KeyError as e:  
                logging.error(f"Key not found: {e}")  
                phase_transitions = []
            
            if phase_transitions:
                phase_list = [item['Phase'] for item in phase_transitions]  
                ts_t_list = [item['Ts']['T'] for item in phase_transitions]  
                ts_t_list_formatted = [ 
                    datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"  for t in ts_t_list 
                ]
            else:
                if phase_transitions_json:
                    #print (phase_transitions_json)
                    phase_transitions = phase_transitions_json
                    
                    phase_list = [item.get('message') for item in phase_transitions]  
                    ts_t_list = [item['time'] for item in phase_transitions]  
                    ts_t_list_formatted = [  
                        datetime.fromisoformat(t).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"  
                        for t in ts_t_list  
                    ]  
        else:
            logging.warning(f"Key 'progress' not found in mongosync_sent_response_body")

        estimated_total_bytes, estimated_total_bytes_unit = format_byte_size(estimated_total_bytes)
        estimated_copied_bytes = convert_bytes(estimated_copied_bytes, estimated_total_bytes_unit)

        logging.info(f"Plotting")

        # Create a subplot for the scatter plots and a separate subplot for the table
        fig = make_subplots(rows=8, cols=2, subplot_titles=("Mongosync Phases", "Estimated Total and Copied " + estimated_total_bytes_unit,
                                                            "Lag Time (seconds)", "Change Events Applied",
                                                            "Collection Copy - Avg and Max Read time (ms)", "Collection Copy Source Reads",
                                                            "Collection Copy - Avg and Max Write time (ms)", "Collection Copy Destination Writes",
                                                            "CEA Source - Avg and Max Read time (ms)", "CEA Source Reads",
                                                            "CEA Destination - Avg and Max Write time (ms)", "CEA Destination Writes",
                                                            "MongoSync Options", 
                                                            "MongoSync Hidden Options",),
                            specs=[ [{}, {}], #Mongosync Phases and Estimated Total and Copied 
                                    [{}, {}], #Lag Time and Events Applied
                                    [{}, {}], #Collection Copy Source
                                    [{}, {}], #Collection Copy Destination
                                    [{}, {}], #CEA Source
                                    [{}, {}], #CEA Destination 
                                    [{"colspan": 2, "type": "table"}, None], 
                                    [{"colspan": 2, "type": "table"}, None] ])

        # Add traces

        # Mongosync Phases
        if phase_transitions:
            fig.add_trace(go.Scatter(x=ts_t_list_formatted, y=phase_list, mode='markers+text',marker=dict(color='green')), row=1, col=1)
            fig.update_yaxes(showticklabels=False, row=1, col=1)  
        else:
            fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Mongosync Finish',textfont=dict(size=30, color="black")), row=1, col=1)
#            fig.update_layout(xaxis5=dict(showgrid=False, zeroline=False, showticklabels=False), 
#                            yaxis5=dict(showgrid=False, zeroline=False, showticklabels=False))

        # Estimated Total and Copied
        #fig = go.Figure(data=[go.Bar(name='Estimated Total Bytes', x=['Bytes'], y=[estimated_total_bytes], row=1, col=1), go.Bar(name='Estimated Copied Bytes', x=['Bytes'], y=[estimated_copied_bytes])], row=1, col=1)
        fig.add_trace( go.Bar( name='Estimated ' + estimated_total_bytes_unit + ' to be Copied',  x=[estimated_total_bytes_unit],  y=[estimated_total_bytes], legendgroup="groupTotalCopied" ), row=1, col=2)
        fig.add_trace( go.Bar( name='Estimated Copied ' + estimated_total_bytes_unit, x=[estimated_total_bytes_unit],  y=[estimated_copied_bytes], legendgroup="groupTotalCopied"), row=1, col=2)

        # Lag Time
        fig.add_trace(go.Scatter(x=times, y=lagTimeSeconds, mode='lines', name='Seconds', legendgroup="groupEventsAndLags"), row=2, col=1)
        #fig.update_yaxes(title_text="Lag Time (seconds)", row=2, col=1)

        # Total Events Applied
        fig.add_trace(go.Scatter(x=times, y=totalEventsApplied, mode='lines', name='Events', legendgroup="groupEventsAndLags"), row=2, col=2)
        #fig.update_yaxes(title_text="Change Events Applied", row=2, col=2)

        # Collection Copy Source Read
        fig.add_trace(go.Scatter(x=times, y=CollectionCopySourceRead, mode='lines', name='Average time (ms)', legendgroup="groupCCSourceRead"), row=3, col=1)
        fig.add_trace(go.Scatter(x=times, y=CollectionCopySourceRead_maximum, mode='lines', name='Maximum time (ms)', legendgroup="groupCCSourceRead"), row=3, col=1)
        #fig.update_yaxes(title_text="Avg and Max time (ms)", secondary_y=False, row=3, col=1)

        fig.add_trace(go.Scatter(x=times, y=CollectionCopySourceRead_numOperations, mode='lines', name='Reads', legendgroup="groupCCSourceRead"), row=3, col=2)
        #fig.update_yaxes(title_text="Number of Reads", secondary_y=True, row=3, col=2)

        #Collection Copy Destination
        fig.add_trace(go.Scatter(x=times, y=CollectionCopyDestinationWrite, mode='lines', name='Average time (ms)', legendgroup="groupCCDestinationWrite"), row=4, col=1)
        fig.add_trace(go.Scatter(x=times, y=CollectionCopyDestinationWrite_maximum, mode='lines', name='Maximum time (ms)', legendgroup="groupCCDestinationWrite"), row=4, col=1)
        #fig.update_yaxes(title_text="Avg and Max time (ms)", secondary_y=False, row=4, col=1)

        fig.add_trace(go.Scatter(x=times, y=CollectionCopyDestinationWrite_numOperations, mode='lines', name='Writes', legendgroup="groupCCDestinationWrite"), row=4, col=2,)
        #fig.update_yaxes(title_text="Number of Writes", secondary_y=True, row=4, col=2)

        #CEA Source
        fig.add_trace(go.Scatter(x=times, y=CEASourceRead, mode='lines', name='Average time (ms)', legendgroup="groupCEASourceRead"), row=5, col=1)
        fig.add_trace(go.Scatter(x=times, y=CEASourceRead_maximum, mode='lines', name='Maximum time (ms)', legendgroup="groupCEASourceRead"), row=5, col=1)
        #fig.update_yaxes(title_text="Avg and Max time (ms)", secondary_y=False, row=5, col=1)

        fig.add_trace(go.Scatter(x=times, y=CEASourceRead_numOperations, mode='lines', name='Reads', legendgroup="groupCEASourceRead"), row=5, col=2)
        #fig.update_yaxes(title_text="Number of Reads", secondary_y=True, row=5, col=2)

        #CEA Destination
        fig.add_trace(go.Scatter(x=times, y=CEADestinationWrite, mode='lines', name='Average time (ms)', legendgroup="groupCEADestinationWrite"), row=6, col=1)
        fig.add_trace(go.Scatter(x=times, y=CEADestinationWrite_maximum, mode='lines', name='Maximum time (ms)', legendgroup="groupCEADestinationWrite"), row=6, col=1)
        #fig.update_yaxes(title_text="Avg and Max time (ms)", secondary_y=False, row=6, col=1)

        fig.add_trace(go.Scatter(x=times, y=CEADestinationWrite_numOperations, mode='lines', name='Writes during CEA', legendgroup="groupCEADestinationWrite"), row=6, col=2)
        #fig.update_yaxes(title_text="Number of Writes", secondary_y=True, row=6, col=2)

        #Add the Mongosync options
        fig.add_trace(table_trace, row=7, col=1)

        #Add the Mongosync options
        fig.add_trace(table_hiddenflags, row=8, col=1)

        # Update layout
        # 225 per plot
        fig.update_layout(height=1800, width=1450, title_text="Mongosync Replication Progress - " + version_text + " - Timezone info: " + timeZoneInfo, legend_tracegroupgap=170, showlegend=False)


        fig.update_layout(
            legend=dict(
                y=1
            )
        )

        # Convert the figure to JSON
        plot_json = json.dumps(fig, cls=PlotlyJSONEncoder)

        logging.info(f"Render the plot in the browse")

        # Render the plot in the browser
        return render_template('upload_results.html', plot_json=plot_json)
