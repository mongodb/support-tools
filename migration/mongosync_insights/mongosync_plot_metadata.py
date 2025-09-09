import configparser
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from plotly.subplots import make_subplots
from flask import request, render_template_string
import json
import logging
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from mongosync_plot_utils import format_byte_size, convert_bytes

def gatherMetrics():
    logging.basicConfig(filename='mongosync_insights.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Reading config file
    config = configparser.ConfigParser()  
    config.read('config.ini')
    
    TARGET_MONGO_URI = config['LiveMonitor']['connectionString']
    internalDb = "mongosync_reserved_for_internal_use"
    colors = ['red', 'blue', 'green', 'orange', 'yellow']
    # Connect to MongoDB cluster
    try:
        clientDst = MongoClient(TARGET_MONGO_URI)
        internalDbDst = clientDst[internalDb]
        logging.info("Connected to target MongoDB cluster.")
    except PyMongoError as e:
        logging.error(f"Failed to connect to target MongoDB: {e}")
        exit(1)
    # Create a subplot for the scatter plots and a separate subplot for the table
    fig = make_subplots(rows=3, 
                        cols=5, 
                        subplot_titles=("Current State", 
                                        "Current Phase",
                                        "Start",
                                        "Finish",

                                        "Partitions Completed %",
                                        "Total X Copied Data",

                                        "Mongosync Phases",
                                        "Collections Progress"),
                        specs=[[{}, {}, None, {}, {}],
                               [{"colspan": 2}, None, None, {"colspan": 2}, None],
                               [{"colspan": 2}, None, None, {"colspan": 2}, None]]                           
                        )

    #Get State and Phase from resumeData collection
    vResumeData = internalDbDst.resumeData.find_one({"_id": "coordinator"})

    #Plot mongosync State
    vState = vResumeData["state"]
    match vState:
        case 'RUNNING':
            vColor = 'blue'
        case "IDDLE":
            vColor = "yellow"
        case "PAUSED":
            vColor = "red"
        case "COMMITTED":
            vColor = "green"
        case _:
            logging.warning(vState +" is not listed as an option")

    fig.add_trace(go.Scatter(x=[0], y=[0], text=[str(vState.capitalize())], mode='text', name='Mongosync State',textfont=dict(size=17, color=vColor)), row=1, col=1)
    fig.update_layout(xaxis1=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis1=dict(showgrid=False, zeroline=False, showticklabels=False))

    #Plot Mongosync State
    vPhase = vResumeData["syncPhase"].capitalize()
    fig.add_trace(go.Scatter(x=[0], y=[0], text=[str(vPhase)], mode='text', name='Mongosync State',textfont=dict(size=17, color="black")), row=1, col=2)
    fig.update_layout(xaxis2=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis2=dict(showgrid=False, zeroline=False, showticklabels=False))

    #Plot Mongosync Start time
    vMatch = {"$match": {"_id": "coordinator"}}
    vAddFields = {"$addFields":{"phaseTransitions": {"$filter": {"input": "$phaseTransitions", "as": "phaseTransitions", 
                  "cond":{"$eq": ["$$phaseTransitions.phase", "initializing collections and indexes"]}
                }}}}
    vProject = {"$project":{"_id": 0, "ts": {"$toDate": {"$arrayElemAt": ["$phaseTransitions.ts" ,0]}}}}
    vInitialData = internalDbDst.resumeData.aggregate([vMatch, vAddFields, vProject])
    vInitialData = list(vInitialData)
    
    if len(vInitialData) > 0:
        for initial in vInitialData:
            newInitial = initial['ts']
    else:
        newInitial = 'NO DATA'

    fig.add_trace(go.Scatter(x=[0], y=[0], text=[str(newInitial)], mode='text', name='Mongosync Start',textfont=dict(size=17, color="black")), row=1, col=4)
    fig.update_layout(xaxis3=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis3=dict(showgrid=False, zeroline=False, showticklabels=False))
    
    #Plot Mongosync Finish time
    vMatch = {"$match": {"_id": "coordinator"}}
    vAddFields = {"$addFields":{"phaseTransitions": {"$filter": {"input": "$phaseTransitions", "as": "phaseTransitions", 
                  "cond":{"$eq": ["$$phaseTransitions.phase", "commit completed"]}
                }}}}
    vProject = {"$project":{"_id": 0, "ts": {"$toDate": {"$arrayElemAt": ["$phaseTransitions.ts" ,0]}}}}
    vFinishData = internalDbDst.resumeData.aggregate([vMatch, vAddFields, vProject])
    vFinishData = list(vFinishData)
    
    if len(vFinishData) > 0:
        for finish in vFinishData:
            newFinish = finish['ts']
    else:
        newFinish = 'NO DATA'

    fig.add_trace(go.Scatter(x=[0], y=[0], text=[str(newFinish)], mode='text', name='Mongosync Finish',textfont=dict(size=17, color="black")), row=1, col=5)
    fig.update_layout(xaxis4=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis4=dict(showgrid=False, zeroline=False, showticklabels=False))

    #Plot partition data

    vGroup1 = {"$group": {"_id": {"namespace": {"$concat": ["$namespace.db", ".", "$namespace.coll"]}, "partitionPhase": "$partitionPhase" },  "documentCount": { "$sum": 1 }}}
    vGroup2 = {"$group": {  "_id": {  "namespace": "$_id.namespace"},  "partitionPhaseCounts": {  "$push": {  "k": "$_id.partitionPhase",  "v": "$documentCount"  }  },  "totalDocumentCount": { "$sum": "$documentCount" }  }  }
    vAddFields1 = {"$addFields": {"namespace": "$_id.namespace"}}
    vProject1 = {"$project": {  "_id": 0,"namespace": 1,"totalDocumentCount": 1,  "partitionPhaseCounts":{"$arrayToObject": "$partitionPhaseCounts" }}  }
    vProject2 = {"$project": {  "_id": 0,"namespace": 1,"totalDocumentCount": 1,  "partitionPhaseCounts": {  "$mergeObjects": [  { "not started": 0, "in progress": 0, "done": 0 },  "$partitionPhaseCounts"  ]  }}  }
    vAddFields2 = {"$addFields": {"PercCompleted": {"$divide": [{ "$multiply": ["$partitionPhaseCounts.done", 100] }, "$totalDocumentCount"]}}}
    vSort1 = {"$sort": {"PercCompleted": 1, "namespace": 1}}  
    vPartitionData = internalDbDst.partitions.aggregate([vGroup1, vGroup2, vAddFields1, vProject1, vProject2, vAddFields2, vSort1])

    vPartitionData = list(vPartitionData)

    #Limits the total of namespaces to 10 in the partitions completed
    if len(vPartitionData) > 10:  
        # Remove PercCompleted == 100  
        filtered = [doc for doc in vPartitionData if doc.get('PercCompleted') != 100]  
        # If we still have more than 10, trim to 10  
        if len(filtered) >= 10:  
            vPartitionData = filtered[:9]  
        else:  
            # If after removal less than 10, fill up with remaining PercCompleted==100  
            needed = 10 - len(filtered)  
            completed_100 = [doc for doc in vPartitionData if doc.get('PercCompleted') == 100]  
            vPartitionData = filtered + completed_100[:needed]  

    if len(vPartitionData) == 0:
        fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Mongosync Finish',textfont=dict(size=30, color="black")), row=2, col=1)
        fig.update_layout(xaxis5=dict(showgrid=False, zeroline=False, showticklabels=False), 
                          yaxis5=dict(showgrid=False, zeroline=False, showticklabels=False))
    else:
        vNamespace = []
        vPercComplete = []        
        for partition in vPartitionData:
            vNamespace.append(partition["namespace"])
            vPercComplete.append(partition["PercCompleted"])
        fig.add_trace(go.Bar(x=vPercComplete, y=vNamespace, orientation='h', 
                             marker=dict(color=vPercComplete, colorscale='blugrn')), row=2, col=1)
        fig.update_xaxes(title_text="Completed %", row=2, col=1)
        fig.update_yaxes(title_text="Namespace", row=2, col=1)
        fig.update_layout(xaxis5=dict(range=[1, 100], dtick=5))

    #Plot complete data
    vGroup = {"$group":{"_id": None, "totalCopiedBytes": { "$sum": "$copiedByteCount" }, "totalBytesCount": { "$sum": "$totalByteCount" }  }}
    vCompleteData = internalDbDst.partitions.aggregate([vGroup])
    vCompleteData=list(vCompleteData)
    vCopiedBytes=0
    vTotalBytes=0
    vTypeByte=['Copied Data', 'Total Data']
    vBytes=[]
    if len(vCompleteData) == 0:
        fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', textfont=dict(size=30, color="black")), row=2, col=4)
        fig.update_layout(xaxis6=dict(showgrid=False, zeroline=False, showticklabels=False), 
                          yaxis6=dict(showgrid=False, zeroline=False, showticklabels=False))
    else:        
        for comp in list(vCompleteData):
            vCopiedBytes=comp["totalCopiedBytes"] + vCopiedBytes
            vTotalBytes=comp["totalBytesCount"] + vTotalBytes
        vTotalBytes, estimated_total_bytes_unit = format_byte_size(vTotalBytes)
        vCopiedBytes = convert_bytes(vCopiedBytes, estimated_total_bytes_unit)
        vBytes.append(vCopiedBytes)
        vBytes.append(vTotalBytes)
        fig.add_trace(go.Bar(x=vBytes, y=vTypeByte, orientation='h',
                             marker=dict(color=vBytes, colorscale='redor')), row=2, col=4)
        fig.update_xaxes(title_text=f"Data in {estimated_total_bytes_unit}", row=2, col=4)
        fig.update_yaxes(title_text="Copied / Total Data", row=2, col=4)
        fig.update_layout(xaxis6=dict(range=[0, vTotalBytes]))

    #Plot Phases transitions
    vMatch = {"$match": {"_id": "coordinator"}}
    vUnwind = {"$unwind": "$phaseTransitions"}
    vProject = {"$project":{"_id": 0, "phase": "$phaseTransitions.phase", "ts": {"$toDate": "$phaseTransitions.ts" }}}
    vTransitionData = internalDbDst.resumeData.aggregate([vMatch, vUnwind, vProject])
    vTransitionData=list(vTransitionData)
    vPhase=[]
    vTs=[]
    if len(vTransitionData) == 0:
        fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', textfont=dict(size=30, color="black")), row=3, col=1)
        fig.update_layout(xaxis7=dict(showgrid=False, zeroline=False, showticklabels=False), 
                          yaxis7=dict(showgrid=False, zeroline=False, showticklabels=False))
    else:        
        for phase in list(vTransitionData):
            vPhase.append(phase["phase"])
            vTs.append(phase["ts"])
        fig.add_trace(go.Scatter(x=vTs, y=vPhase, mode='markers+text',marker=dict(color='green')), row=3, col=1)
    
    #Colection Progress
    vProject1 = {"$project": {  "namespace": {  "$concat": ["$namespace.db", ".", "$namespace.coll"]  },  "partitionPhase": 1  }}
    vGroup1 = {"$group": {  "_id": "$namespace",  "phases": { "$addToSet": "$partitionPhase" }  } }
    vProject2 = {"$project": {  "_id": 0,  "namespace": "$_id",  "phases": {  "$arrayToObject": {  "$map": {  "input": "$phases",  "as": "phase",  "in": { "k": "$$phase", "v": 1 }  }  }  }  }}
    vProject3 = {"$project": {  "_id": 0,"namespace": 1,  "phases": {  "$mergeObjects": [  { "not started": 0, "in progress": 0, "done": 0 },  "$phases"  ]  }}  }

    vCollectionData = internalDbDst.partitions.aggregate([vProject1, vGroup1, vProject2, vProject3])

    vCollectionData = list(vCollectionData)

    vTypeProc=[]
    vTypeValue=[]
    if len(vCollectionData) == 0:
        fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', textfont=dict(size=30, color="black")), row=3, col=4)
        fig.update_layout(xaxis8=dict(showgrid=False, zeroline=False, showticklabels=False), 
                          yaxis8=dict(showgrid=False, zeroline=False, showticklabels=False))
    else:
        NotStarted = 0
        InProgress = 0
        Done = 0
        for collec in vCollectionData:
            if ((collec["phases"]["in progress"] == 1) or (collec["phases"]["not started"] == 1 and collec["phases"]["done"] == 1)):
                InProgress += 1
            elif (collec["phases"]["not started"] == 1 and collec["phases"]["done"] != 1):
                NotStarted += 1
            else:
                Done += 1
            
        vTypeProc.append("Not Started")
        vTypeValue.append(NotStarted)
        vTypeProc.append("In Progress")
        vTypeValue.append(InProgress)
        vTypeProc.append("Completed")
        vTypeValue.append(Done)
        xMin = min(vTypeValue)
        xMax = max(vTypeValue)

        fig.add_trace(go.Bar(x=vTypeValue, y=vTypeProc, orientation='h',
                             marker=dict(color=vTypeValue, colorscale='Oryel')), row=3, col=4)
        fig.update_xaxes(title_text=f"Totals", row=3, col=4)
        fig.update_yaxes(title_text="Process", row=3, col=4)
        fig.update_layout(xaxis8=dict(range=[0, xMax])) 
    
    # Update layout
    fig.update_layout(height=850, width=1450, autosize=True, title_text="Mongosync Replication Progress - Timezone info: UTC", showlegend=False, plot_bgcolor="white")
    
    # Convert the figure to JSON
    plot_json = json.dumps(fig, cls=PlotlyJSONEncoder)
    return plot_json


def plotMetrics():
    # Reading config file
    config = configparser.ConfigParser()  
    config.read('config.ini')

    refreshTime = config['LiveMonitor']['refreshTime']
    refreshTimeMs = str(int(refreshTime) * 1000)
    
    return render_template_string('''
            <!DOCTYPE html>  
            <html lang="en">  
            <head>  
                <meta charset="UTF-8">  
                <title>Mongosync Insights</title>  
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
                        background-color: #00684A;  
                        color: #fff;  
                        padding: 10px 20px;  
                        text-align: center;  
                    }  
            
                    main {  
                        padding: 20px;  
                    }  
            
                    #plot {  
                        margin: 0 auto;  
                        max-width: 1450px;  
                        border: 1px solid #ccc; /* Add border for distinction */  
                        border-radius: 8px; /* Rounded corners */  
                        background-color: #fff;  
                        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.2); /* Subtle shadow for depth */  
                    }  
            
                    footer {  
                        text-align: center;  
                        padding: 10px;  
                        margin-top: 20px;  
                        background-color: #00684A;  
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
                    <h1>Mongosync Insights - Metadata</h1>  
                </header>  
                <main>  
                    <div id="loading">Loading metrics...</div>
                    <div id="plot" style="display:none;"></div>

            <script>
                async function fetchPlotData() {
                    try {
                        const response = await fetch("/get_metrics_data", { method: 'POST' });
                        const plotData = await response.json();
                        document.getElementById("loading").style.display = "none";
                        document.getElementById("plot").style.display = "block";
                        Plotly.react('plot', plotData.data, plotData.layout);
                    } catch (err) {
                        console.error("Error fetching data:", err);
                        document.getElementById("loading").innerText = "Error loading data.";
                    }
                }

                fetchPlotData(); // initial load
                setInterval(fetchPlotData, ''' + refreshTimeMs + '''); // update every ''' + refreshTime + ''' seconds
            </script>

            </main>  
                <footer>  
                    <!-- <p>&copy; 2023 MongoDB. All rights reserved.</p>  -->
                    <p>Refresing every '''+ refreshTime +''' seconds - Version 0.6.5</p>
                </footer>  
            </body>  
            </html>  
    ''')