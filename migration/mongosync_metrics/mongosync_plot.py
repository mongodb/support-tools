from flask import Flask, render_template_string
from mongosync_plot_logs import upload_file
from mongosync_plot_metadata import plotMetrics, gatherMetrics

# Create a Flask app
app = Flask(__name__)

@app.route('/')
def upload_form():
    # Return a simple file upload form
    return render_template_string ('''
        <!DOCTYPE html>  
        <html>  
            <head>  
                <title>Mongosync Metrics</title>  
                <style>  
                    /* Create a container for the forms */  
                    .form-container {  
                        display: flex; /* Use flexbox to align forms side by side */  
                        gap: 20px; /* Add space between the forms */  
                        justify-content: center; /* Center the forms horizontally */  
                        align-items: flex-start; /* Align forms to the top */  
                    }  
        
                    /* Style individual forms */  
                    form {  
                        width: 350px; /* Set a width for the forms */  
                        border: 1px solid #ccc; /* Add a border */  
                        padding: 20px; /* Add padding inside the form */  
                        border-radius: 8px; /* Optional: rounded corners */  
                        background-color: #f9f9f9; /* Optional: light background color */  
                        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1); /* Optional: add shadow for aesthetics */  
                    }  
        
                    /* Style the body of the page */  
                    body {  
                        font-family: Arial, sans-serif; /* Use a clean font */  
                        margin: 0;  
                        padding: 0;  
                        display: flex;  
                        justify-content: center;  
                        align-items: center;  
                        height: 100vh; /* Make the page take the full viewport height */  
                        background-color: #ffffff; /* Background color */  
                    }  
        
                    /* Optional: Style images */  
                    img {  
                        max-width: 100%; /* Ensure images fit within the container */  
                        border: 1px solid #ccc; /* Add border to images */  
                        border-radius: 8px; /* Add rounded corners (optional) */  
                    }  
                </style>  
            </head>  
            <body>  
                <div class="form-container">  
                    <!-- First form: File upload -->  
                    <form method="post" action="/upload" enctype="multipart/form-data">  
                        <h2>Upload Mongosync Log File</h2>  
                        <input type="file" name="file"><br><br>  
                        <input type="submit" value="Upload">  
                        <p>This form allows you to upload a mongosync log file. Once the file is uploaded, the application will process the data and generate plots.</p>  
                        <img src="static/mongosync_log_analyzer.png" width="300" alt="Mongosync Log Analyzer">  
                    </form>  
        
                    <!-- Second form: Metrics rendering -->  
                    <form method="post" action="/renderMetrics" enctype="multipart/form-data">  
                        <h2>Render Metada Metrics</h2>  
                        <input type="submit" value="Read Metadata">  
                        <p>Click this button to generate the plost using mongosync metadata.</p>
                        <img src="static/mongosync_metadata.png" width="300" alt="Mongosync Log Analyzer">
                    </form>  
                </div>  
            </body>  
        </html>  
                                   ''')


@app.route('/upload', methods=['POST'])
def uploadLogs():
    return upload_file()

@app.route('/renderMetrics', methods=['POST'])
def renderMetrics():
    return plotMetrics()

@app.route('/get_metrics_data', methods=['POST'])
def getMetrics():
    return gatherMetrics()

if __name__ == '__main__':
    # Run the Flask app
    app.run(host='0.0.0.0', port=3030)
