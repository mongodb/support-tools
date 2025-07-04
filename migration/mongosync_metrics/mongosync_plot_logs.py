import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from plotly.subplots import make_subplots
from tqdm import tqdm
from flask import request, redirect, render_template_string
import json
from datetime import datetime
import re
from mongosync_plot_utils import format_byte_size, convert_bytes

def upload_file():
    # Check if a file was uploaded
    if 'file' not in request.files:
        return redirect(request.url)

    file = request.files['file']

    # If the user does not select a file, the browser submits an
    # empty file without a filename.
    if file.filename == '':
        return redirect(request.url)

    if file:
        # Read the file and convert it to a list of lines
        lines = list(file)

        # Check if all lines are valid JSON
        for line in tqdm(lines, desc="Reading lines"):
            try:
                json.loads(line)
            except json.JSONDecodeError:
                print(f"Invalid JSON: {line}")
                return redirect(request.url)  # or handle the error in another appropriate way

        # Load lines with 'message' == "Replication progress."
        #data = [json.loads(line) for line in lines if json.loads(line).get('message') == "Replication progress."]
        regex_pattern = re.compile(r"Replication progress", re.IGNORECASE)
        data = [
            json.loads(line) 
            for line in lines 
            if regex_pattern.search(json.loads(line).get('message', ''))
        ]

        # Load lines with 'message' == "Version info"
        #version_info_list = [json.loads(line) for line in lines if json.loads(line).get('message') == "Version info"]
        regex_pattern = re.compile(r"Version info", re.IGNORECASE)
        version_info_list = [
            json.loads(line) 
            for line in lines 
            if regex_pattern.search(json.loads(line).get('message', ''))
        ]

        # Load lines with 'message' == "Mongosync Options"
        #mongosync_opts_list = [json.loads(line) for line in lines if json.loads(line).get('message') == "Mongosync Options"]
        regex_pattern = re.compile(r"Mongosync Options", re.IGNORECASE)
        mongosync_opts_list = [
            json.loads(line) 
            for line in lines 
            if regex_pattern.search(json.loads(line).get('message', ''))
        ]

        # Load lines with 'message' == "Operation duration stats."
        #mongosync_ops_stats = [json.loads(line) for line in lines if json.loads(line).get('message') == "Operation duration stats."]
        regex_pattern = re.compile(r"Operation duration stats", re.IGNORECASE)
        mongosync_ops_stats = [
            json.loads(line) 
            for line in lines 
            if regex_pattern.search(json.loads(line).get('message', ''))
        ]

        # Load lines with 'message' == "sent response"
        #mongosync_sent_response = [json.loads(line) for line in lines if json.loads(line).get('message') == "Sent response."]
        regex_pattern = re.compile(r"sent response", re.IGNORECASE)
        mongosync_sent_response = [
            json.loads(line) 
            for line in lines 
            if regex_pattern.search(json.loads(line).get('message', ''))
        ]

        # Load lines with 'message' == "Mongosync HiddenFlags"
        regex_pattern = re.compile(r"Mongosync HiddenFlags", re.IGNORECASE)
        mongosync_hiddenflags = [
            json.loads(line) 
            for line in lines 
            if regex_pattern.search(json.loads(line).get('message', ''))
        ]

        # The 'body' field is also a JSON string, so parse that as well
        #mongosync_sent_response_body = json.loads(mongosync_sent_response.get('body'))
        for response in mongosync_sent_response:
            mongosync_sent_response_body  = json.loads(response['body'])
            # Now you can work with the 'body' data

        # Create a string with all the Mongosync Options information
        mongosync_opts_text = "\n".join([json.dumps(item, indent=4) for item in mongosync_opts_list])

        # Create a string with all the version information
        version_text = "\n".join([f"MongoSync Version: {item.get('version')}, OS: {item.get('os')}, Arch: {item.get('arch')}" for item in version_info_list])

        # Extract the keys from the mongosync_hiddenflags
        # For each key, extract the corresponding values from mongosync_hiddenflags
        if mongosync_hiddenflags:
            keys = list(mongosync_hiddenflags[0].keys())
            values = [[str(item[key]).replace('{', '').replace('}', '')  for item in mongosync_hiddenflags] for key in keys]

            # Create a table trace with the keys as the first column and the corresponding values as the second column
            table_hiddenflags = go.Table(
                header=dict(values=['Key', 'Value'], font=dict(size=12, color='black')),
                cells=dict(values=[keys, values],  align=['left'], font=dict(size=10, color='darkblue')), #
                columnwidth=[0.75, 2.5]  # Adjust the column widths as needed
            )
        else:
            #print("mongosync_hiddenflags is empty")
            table_hiddenflags = go.Table(
                header=dict(values=['Mongosync Hidden Flags']),
                cells=dict(values=[["No Mongosync Hidden Flags found in the log file"]])
            )
        
        if mongosync_opts_list:
            keys = list(mongosync_opts_list[0].keys())
            values = [[item[key] for item in mongosync_opts_list] for key in keys]

            # Create a table trace with the keys as the first column and the corresponding values as the second column
            table_trace = go.Table(
                header=dict(values=['Key', 'Value'], font=dict(size=12, color='black')),
                cells=dict(values=[keys, values], font=dict(size=10, color='darkblue')),
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
            #print("mongosync_opts_list is empty")
            table_trace = go.Table(header=dict(values=['Mongosync Options']),
            cells=dict(values=[["No Mongosync Options found in the log file"]]))

        #Getting the Timezone
        #print (data[0]['time'])
        datetime_with_timezone = datetime.fromisoformat(data[0]['time'].replace('Z', '+00:00'))  
        timeZoneInfo = datetime_with_timezone.strftime("%Z")

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

        if 'progress' in mongosync_sent_response_body:
            estimated_total_bytes = mongosync_sent_response_body['progress']['collectionCopy']['estimatedTotalBytes']
            estimated_copied_bytes = mongosync_sent_response_body['progress']['collectionCopy']['estimatedCopiedBytes']
        else:
            print("Key 'progress' not found in mongosync_sent_response_body")

        estimated_total_bytes, estimated_total_bytes_unit = format_byte_size(estimated_total_bytes)
        estimated_copied_bytes = convert_bytes(estimated_copied_bytes, estimated_total_bytes_unit)

        # Create a subplot for the scatter plots and a separate subplot for the table
        fig = make_subplots(rows=8, cols=2, subplot_titles=("Estimated Total and Copied " + estimated_total_bytes_unit,
                                                            "Lag Time (seconds)", "Change Events Applied",
                                                            "Collection Copy Read Avg and Max time", "Collection Copy Source Reads",
                                                            "Collection Copy Write Avg and Max time", "Collection Copy Destination Writes",
                                                            "CEA Source Read Avg and Max time", "CEA Source Reads",
                                                            "CEA Destination Write Avg and Max time", "CEA Destination Writes",
                                                            "MongoSync Options", 
                                                            "MongoSync Hidden Options",),
                            #specs=[ [{}], #Estimated Total and Copied 
                            #        [{}], #Lag Time
                            #        [{}], #Events Applied
                            #        [{"secondary_y": True}], 
                            #        [{"secondary_y": True}], 
                            #        [{"secondary_y": True}], 
                            #        [{"secondary_y": True}], 
                            #        [{"type": "table"}], 
                            #        [{"type": "table"}] ])
                            specs=[ [{"colspan": 2}, None], #Estimated Total and Copied 
                                    [{}, {}], #Lag Time and Events Applied
                                    [{}, {}], #Collection Copy Source
                                    [{}, {}], #Collection Copy Destination
                                    [{}, {}], #CEA Source
                                    [{}, {}], #CEA Destination 
                                    [{"colspan": 2, "type": "table"}, None], 
                                    [{"colspan": 2, "type": "table"}, None] ])

        # Add traces

        # Create a bar chart
        #fig = go.Figure(data=[go.Bar(name='Estimated Total Bytes', x=['Bytes'], y=[estimated_total_bytes], row=1, col=1), go.Bar(name='Estimated Copied Bytes', x=['Bytes'], y=[estimated_copied_bytes])], row=1, col=1)
        fig.add_trace( go.Bar( name='Estimated ' + estimated_total_bytes_unit + ' to be Copied',  x=[estimated_total_bytes_unit],  y=[estimated_total_bytes], legendgroup="groupTotalCopied" ), row=1, col=1)
        fig.add_trace( go.Bar( name='Estimated Copied ' + estimated_total_bytes_unit, x=[estimated_total_bytes_unit],  y=[estimated_copied_bytes], legendgroup="groupTotalCopied"), row=1, col=1)

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
        fig.update_layout(height=1800, width=1250, title_text="Mongosync Replication Progress - " + version_text + " - Timezone info: " + timeZoneInfo, legend_tracegroupgap=170, showlegend=False)


        fig.update_layout(
            legend=dict(
                y=1
            )
        )

        # Convert the figure to JSON
        plot_json = json.dumps(fig, cls=PlotlyJSONEncoder)

        # Render the plot in the browser
        return render_template_string('''
            <!DOCTYPE html>  
            <html lang="en">  
            <head>  
                <meta charset="UTF-8">  
                <title>Mongosync Metrics Visualization</title>  
                <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>  
                <style>  
                    body {  
                        font-family: Arial, sans-serif;  
                        margin: 0;  
                        padding: 0;  
                        background-color: #f4f4f9; /* Light background for good contrast */  
                        color: #333; /* Dark text for readability */  
                    }  
            
                    header {  
                        background-color: #005d95;  
                        color: #fff;  
                        padding: 10px 20px;  
                        text-align: center;  
                    }  
            
                    main {  
                        padding: 20px;  
                    }  
            
                    #plot {  
                        margin: 0 auto;  
                        max-width: 1250px;  
                        border: 1px solid #ccc; /* Add border for distinction */  
                        border-radius: 8px; /* Rounded corners */  
                        background-color: #fff;  
                        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.2); /* Subtle shadow for depth */  
                    }  
            
                    footer {  
                        text-align: center;  
                        padding: 10px;  
                        margin-top: 20px;  
                        background-color: #005d95;  
                        color: #fff;  
                    }  
            
                    @media (max-width: 768px) {  
                        #plot {  
                            width: 95%; /* Make responsive for smaller screens */  
                        }  
                    }  
                </style>  
            </head>  
            <body>  
                <header>  
                    <h1>Mongosync Metrics - Logs</h1>  
                </header>  
                <main>  
                    <div id="plot"></div>  
                    <script>
                    var plot = {{ plot_json | safe }};
                    Plotly.newPlot('plot', plot.data, plot.layout);
                    </script>
                </main>  
                <footer>  
                    <!-- <p>&copy; 2023 MongoDB. All rights reserved.</p>  -->
                </footer>  
            </body>  
            </html>  
        ''', plot_json=plot_json)
    
""" @app.route('/plot')
def serve_plot():
    file_path = os.path.join(app.static_folder, 'plot.png')
    print(file_path)  # print the file path

    if os.path.exists(file_path):
        return send_from_directory(app.static_folder, 'plot.png')
    else:
        return "File not found", 404 """