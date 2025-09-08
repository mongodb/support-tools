import configparser
import logging
from flask import Flask, render_template_string, request
from mongosync_plot_logs import upload_file
from mongosync_plot_metadata import plotMetrics, gatherMetrics
from pymongo.uri_parser import parse_uri  
from pymongo.errors import InvalidURI 

# Reading config file
config = configparser.ConfigParser()  
config.read('config.ini')

# Setting the script log file
logging.basicConfig(filename='mongosync_insights.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Create a Flask app
app = Flask(__name__)

@app.route('/')
def home_page(message = ""):

    if message == "invalid connection string":
        connectionStringForm = ''' <label for="connectionString"><b>The connection string provided is invalid, please provide a valid connection string.</b></label>  
                                    <input type="text" id="connectionString" name="connectionString" size="47"   
                                        placeholder="mongodb+srv://usr:pwd@cluster0.mongodb.net/myDB"><br><br>
                                '''
    elif not config['LiveMonitor']['connectionString']:
        connectionStringForm =  ''' <label for="connectionString">Atlas MongoDB Connection String:</label>  
                                    <input type="text" id="connectionString" name="connectionString" size="47"   
                                        placeholder="mongodb+srv://usr:pwd@cluster0.mongodb.net/myDB"><br><br>
                                '''
    else:
        parsed = parse_uri(config['LiveMonitor']['connectionString'])  
        hosts = parsed['nodelist']
        hosts_str = ", ".join([f"{host}:{port}" for host, port in hosts])  
        connectionStringForm = "<p><b>Connecting to Destination Cluster at: </b>"+hosts_str+"</p>"


    # Return a simple file upload form
    return render_template_string ('''
        <!DOCTYPE html>  
        <html>  
            <head>  
                <title>Mongosync Insights</title>  
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
                <div style="position: absolute; top: 20px; left: 50%; transform: translateX(-50%); text-align: center;">  
                    <h1 style="margin-bottom: 0;">Mongosync Insights <span style="font-size:0.6em;color:#777;">v0.6.6</span></h1>  
                </div>    
                <div class="form-container">  
                    <!-- First form: File upload -->  
                    <form method="post" action="/upload" enctype="multipart/form-data">  
                        <h2>Parse Mongosync Log File</h2>  
                        <input type="file" name="file"><br><br>  
                        <input type="submit" value="Upload">  
                        <p>Click the "Upload" button after selecting your Mongosync log file to generate migration progress plots.</p>  
                        <img src="static/mongosync_log_analyzer.png" width="300" alt="Mongosync Log Analyzer">  
                    </form>  
        
                    <!-- Second form: Metrics rendering -->  
                    <form id="metadataForm" method="post" action="/renderMetrics" enctype="multipart/form-data" onsubmit="return checkAtlasConnection();">   
                        <h2>Live Migration Monitoring</h2>''' + 
                        
                        connectionStringForm +

                    '''    
                        <input type="submit" value="Live Monitor">  
                        <p>Click the “Live Monitor” button to start monitoring the migration progress in real time.</p>
                        <img src="static/mongosync_metadata.png" width="300" alt="Mongosync Log Analyzer">
                    </form>

                            <script>  
                            function checkAtlasConnection() {  
                                var conn = document.getElementById('connectionString').value.trim();  
                                if (!conn) {  
                                    alert("Please enter the Atlas MongoDB Connection String.");  
                                    return false; // Prevent form submission  
                                }  
                                return true; // Proceed with submission  
                            }  
                            </script>  
                </div>
                <!--
                    <div style="position:fixed; bottom:20px; left:50%; transform:translateX(-50%); color:#888; font-size:0.9em;">  
                        Mongosync Insights v1.2.0  
                    </div>   
                -->
            </body>  
        </html>  
                                   ''')


@app.route('/upload', methods=['POST'])
def uploadLogs():
    return upload_file()

@app.route('/renderMetrics', methods=['POST'])
def renderMetrics():

    refreshTime = config['LiveMonitor']['refreshTime']

    # If the connectionString is empty in the config.ini, get it from the form and save in the file.
    if config['LiveMonitor']['connectionString']:
        TARGET_MONGO_URI = config['LiveMonitor']['connectionString']
    else:
        TARGET_MONGO_URI = request.form.get('connectionString')
        config['LiveMonitor']['connectionString'] = TARGET_MONGO_URI
        config['LiveMonitor']['refreshTime'] = refreshTime
        with open('config.ini', 'w') as configfile:  
            config.write(configfile) 

    # Validate the connection string 
    # If valid proceed to plot
    # If not, return to home 
    try:  
        parse_uri(TARGET_MONGO_URI)  
        return plotMetrics()
    except InvalidURI as e:  
        logging.error(f"{e}. Invalid MongoDB connection string: "+ TARGET_MONGO_URI)
        
        config['LiveMonitor']['connectionString'] = ""
        config['LiveMonitor']['refreshTime'] = refreshTime
        with open('config.ini', 'w') as configfile:  
            config.write(configfile)   
        
        return home_page("invalid connection string")

    #return plotMetrics()

@app.route('/get_metrics_data', methods=['POST'])
def getMetrics():
    return gatherMetrics()

if __name__ == '__main__':
    # Run the Flask app
    app.run(host='0.0.0.0', port=3030)
