import configparser
import logging
from flask import Flask, render_template, request
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
def home_page(message=""):
    if message == "invalid connection string":
        connection_string_form = '''<label for="connectionString"><b>The connection string provided is invalid, please provide a valid connection string.</b></label>  
                                    <input type="text" id="connectionString" name="connectionString" size="47"   
                                        placeholder="mongodb+srv://usr:pwd@cluster0.mongodb.net/myDB"><br><br>'''
    elif not config['LiveMonitor']['connectionString']:
        connection_string_form = '''<label for="connectionString">Atlas MongoDB Connection String:</label>  
                                    <input type="text" id="connectionString" name="connectionString" size="47"   
                                        placeholder="mongodb+srv://usr:pwd@cluster0.mongodb.net/myDB"><br><br>'''
    else:
        parsed = parse_uri(config['LiveMonitor']['connectionString'])  
        hosts = parsed['nodelist']
        hosts_str = ", ".join([f"{host}:{port}" for host, port in hosts])  
        connection_string_form = f"<p><b>Connecting to Destination Cluster at: </b>{hosts_str}</p>"

    return render_template('home.html', connection_string_form=connection_string_form)


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
