import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from plotly.subplots import make_subplots
from flask import request, render_template
import json
import logging
import textwrap
import requests
from datetime import datetime, timezone
from bson import Timestamp
from pymongo.errors import PyMongoError
from mongosync_plot_utils import format_byte_size, convert_bytes


def get_phase_timestamp(phase_transitions, phase_name):
    """Find the first matching phase and return its timestamp as datetime."""
    if not phase_transitions:
        return None
    for pt in phase_transitions:
        if pt.get("phase") == phase_name:
            ts = pt.get("ts")
            if isinstance(ts, Timestamp):
                return datetime.fromtimestamp(ts.time, tz=timezone.utc)
            elif isinstance(ts, datetime):
                return ts
    return None

def gatherMetrics(connection_string):
    # Use the centralized logging and configuration
    logger = logging.getLogger(__name__)
    
    # Import and use the centralized configuration
    from app_config import INTERNAL_DB_NAME, get_database
    
    TARGET_MONGO_URI = connection_string
    internalDb = INTERNAL_DB_NAME
    
    # Connect to MongoDB cluster using connection pooling
    try:
        internalDbDst = get_database(TARGET_MONGO_URI, internalDb)
        logger.info("Connected to target MongoDB cluster using connection pooling.")
    except PyMongoError as e:
        logger.error(f"Failed to connect to target MongoDB: {e}")
        exit(1)
    # Create a subplot for status information only (2 rows)
    fig = make_subplots(rows=2, 
                        cols=5, 
                        row_heights=[0.5, 0.5],
                        subplot_titles=("Current State", 
                                        "Current Phase",
                                        "Lag Time",
                                        "Start",
                                        "Finish",

                                        "Reversible",
                                        "Write Blocking Mode",
                                        "Build Indexes",
                                        "Detect Random Id",
                                        "Embedded Verifier"),
                        specs=[[{}, {}, {}, {}, {}],
                               [{}, {}, {}, {}, {}]]                           
                        )

    #Get State and Phase from resumeData collection
    vResumeData = internalDbDst.resumeData.find_one({"_id": "coordinator"})

    #Plot mongosync State
    vState = vResumeData["state"]
    if vState == 'RUNNING':
        vColor = 'blue'
    elif vState == "IDLE":
        vColor = "yellow"
    elif vState == "PAUSED":
        vColor = "red"
    elif vState == "COMMITTED":
        vColor = "green"
    else:
        logging.warning(vState + " is not listed as an option")
        vColor = "gray"
    
    #Plot Mongosync State
    fig.add_trace(go.Scatter(x=[0], y=[0], text=[str(vState)], mode='text', name='Mongosync State',textfont=dict(size=17, color=vColor)), row=1, col=1)
    fig.update_layout(xaxis1=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis1=dict(showgrid=False, zeroline=False, showticklabels=False))

    #Plot Mongosync Phase
    vPhase = vResumeData["syncPhase"].capitalize()
    wrapped_phase = "<br>".join(textwrap.wrap(str(vPhase), width=15))
    fig.add_trace(go.Scatter(x=[0], y=[0], text=[wrapped_phase], mode='text', name='Mongosync Phase',textfont=dict(size=17, color="black")), row=1, col=2)
    fig.update_layout(xaxis2=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis2=dict(showgrid=False, zeroline=False, showticklabels=False))

    #Plot Lag Time (calculated from crudChangeStreamResumeInfo.lastEventTs)
    def format_lag_duration(delta):
        """Format a timedelta as a human-readable string."""
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return "0s"
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        return " ".join(parts)

    def get_last_event_datetime(resume_info):
        """Extract lastEventTs from resume info and convert to datetime."""
        if not resume_info:
            return None
        lastEventTs = resume_info.get("lastEventTs")
        if not lastEventTs:
            return None
        if isinstance(lastEventTs, Timestamp):
            return datetime.fromtimestamp(lastEventTs.time, tz=timezone.utc)
        elif isinstance(lastEventTs, datetime):
            return lastEventTs if lastEventTs.tzinfo else lastEventTs.replace(tzinfo=timezone.utc)
        return None

    lagTimeText = 'NO DATA'
    crudChangeStreamResumeInfo = vResumeData.get("crudChangeStreamResumeInfo") if vResumeData else None
    ddlChangeStreamResumeInfo = vResumeData.get("ddlChangeStreamResumeInfo") if vResumeData else None
    
    crudLastEventDt = get_last_event_datetime(crudChangeStreamResumeInfo)
    ddlLastEventDt = get_last_event_datetime(ddlChangeStreamResumeInfo)
    
    # Use the most recent timestamp between crud and ddl
    lastEventDt = None
    if crudLastEventDt and ddlLastEventDt:
        lastEventDt = max(crudLastEventDt, ddlLastEventDt)
    elif crudLastEventDt:
        lastEventDt = crudLastEventDt
    elif ddlLastEventDt:
        lastEventDt = ddlLastEventDt
    
    if lastEventDt:
        currentTime = datetime.now(tz=timezone.utc)
        lagDuration = currentTime - lastEventDt
        lagTimeText = format_lag_duration(lagDuration)

    fig.add_trace(go.Scatter(x=[0], y=[0], text=[lagTimeText], mode='text', name='Lag Time',textfont=dict(size=17, color="black")), row=1, col=3)
    fig.update_layout(xaxis3=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis3=dict(showgrid=False, zeroline=False, showticklabels=False))

    #Plot Mongosync Start time (using phaseTransitions from vResumeData)
    phaseTransitions = vResumeData.get("phaseTransitions", []) if vResumeData else []
    newInitial = get_phase_timestamp(phaseTransitions, "initializing collections and indexes")
    if newInitial is None:
        newInitialText = 'NO DATA'
    else:
        newInitialText = newInitial.strftime("%Y-%m-%d %H:%M:%S")

    fig.add_trace(go.Scatter(x=[0], y=[0], text=[newInitialText], mode='text', name='Mongosync Start',textfont=dict(size=17, color="black")), row=1, col=4)
    fig.update_layout(xaxis4=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis4=dict(showgrid=False, zeroline=False, showticklabels=False))
    
    #Plot Mongosync Finish time (using phaseTransitions from vResumeData)
    newFinish = get_phase_timestamp(phaseTransitions, "commit completed")
    if newFinish is None:
        newFinishText = 'NO DATA'
    else:
        newFinishText = newFinish.strftime("%Y-%m-%d %H:%M:%S")

    fig.add_trace(go.Scatter(x=[0], y=[0], text=[newFinishText], mode='text', name='Mongosync Finish',textfont=dict(size=17, color="black")), row=1, col=5)
    fig.update_layout(xaxis5=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis5=dict(showgrid=False, zeroline=False, showticklabels=False))

    #Plot globalState values
    vGlobalState = internalDbDst.globalState.find_one({})
    
    #Plot Reversible
    reversibleValue = str(vGlobalState.get("reversible", "NO DATA")) if vGlobalState else "NO DATA"
    fig.add_trace(go.Scatter(x=[0], y=[0], text=[reversibleValue], mode='text', name='Reversible',textfont=dict(size=17, color="black")), row=2, col=1)
    fig.update_layout(xaxis6=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis6=dict(showgrid=False, zeroline=False, showticklabels=False))
    
    #Plot Write Blocking Mode
    writeBlockingModeRaw = vGlobalState.get("writeBlockingMode") if vGlobalState else None
    if writeBlockingModeRaw == "destinationOnly":
        writeBlockingModeValue = "Destination Only"
    elif writeBlockingModeRaw == "sourceAndDestination":
        writeBlockingModeValue = "Source and Destination"
    elif writeBlockingModeRaw == "none":
        writeBlockingModeValue = "None"
    else:
        writeBlockingModeValue = "NO DATA"
    fig.add_trace(go.Scatter(x=[0], y=[0], text=[writeBlockingModeValue], mode='text', name='Write Blocking Mode',textfont=dict(size=17, color="black")), row=2, col=2)
    fig.update_layout(xaxis7=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis7=dict(showgrid=False, zeroline=False, showticklabels=False))
    
    #Plot Build Indexes
    buildIndexesRaw = vGlobalState.get("buildIndexes") if vGlobalState else None
    if buildIndexesRaw == "afterDataCopy":
        buildIndexesValue = "After Data Copy"
    elif buildIndexesRaw == "beforeDataCopy":
        buildIndexesValue = "Before Data Copy"
    elif buildIndexesRaw == "never":
        buildIndexesValue = "Never"
    else:
        buildIndexesValue = "NO DATA"
    fig.add_trace(go.Scatter(x=[0], y=[0], text=[buildIndexesValue], mode='text', name='Build Indexes',textfont=dict(size=17, color="black")), row=2, col=3)
    fig.update_layout(xaxis8=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis8=dict(showgrid=False, zeroline=False, showticklabels=False))
    
    #Plot Detect Random Id
    detectRandomIdValue = str(vGlobalState.get("detectRandomId", "NO DATA")) if vGlobalState else "NO DATA"
    fig.add_trace(go.Scatter(x=[0], y=[0], text=[detectRandomIdValue], mode='text', name='Detect Random Id',textfont=dict(size=17, color="black")), row=2, col=4)
    fig.update_layout(xaxis9=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis9=dict(showgrid=False, zeroline=False, showticklabels=False))
    
    #Plot Verification Mode
    verificationModeValue = str(vGlobalState.get("verificationmode", "NO DATA")).capitalize() if vGlobalState else "NO DATA"
    fig.add_trace(go.Scatter(x=[0], y=[0], text=[verificationModeValue], mode='text', name='Embedded Verifier',textfont=dict(size=17, color="black")), row=2, col=5)
    fig.update_layout(xaxis10=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis10=dict(showgrid=False, zeroline=False, showticklabels=False))
    
    # Update layout
    fig.update_layout(height=450, width=1550, autosize=True, title_text="Mongosync Status - Timezone info: UTC", showlegend=False, plot_bgcolor="white")
    
    # Convert the figure to JSON
    plot_json = json.dumps(fig, cls=PlotlyJSONEncoder)
    return plot_json


def gatherPartitionsMetrics(connection_string):
    """Generate progress view with partitions, data copy, phases, and collection progress."""
    logger = logging.getLogger(__name__)
    
    from app_config import INTERNAL_DB_NAME, MAX_PARTITIONS_DISPLAY, get_database
    
    TARGET_MONGO_URI = connection_string
    internalDb = INTERNAL_DB_NAME
    
    try:
        internalDbDst = get_database(TARGET_MONGO_URI, internalDb)
        logger.info("Connected to target MongoDB for progress metrics.")
    except PyMongoError as e:
        logger.error(f"Failed to connect to target MongoDB: {e}")
        exit(1)
    
    # Create subplots for progress view (2x2 grid)
    fig = make_subplots(
        rows=2, 
        cols=2, 
        row_heights=[0.5, 0.5],
        subplot_titles=(
            "Partitions Completed %",
            "Total X Copied Data",
            "Mongosync Phases",
            "Collections Progress"
        ),
        horizontal_spacing=0.15,
        vertical_spacing=0.2
    )
    
    # Get resumeData for phase transitions
    vResumeData = internalDbDst.resumeData.find_one({"_id": "coordinator"})
    phaseTransitions = vResumeData.get("phaseTransitions", []) if vResumeData else []
    
    # 1. Partitions Completed % (Row 1, Col 1)
    vGroup1 = {"$group": {"_id": {"namespace": {"$concat": ["$namespace.db", ".", "$namespace.coll"]}, "partitionPhase": "$partitionPhase" },  "documentCount": { "$sum": 1 }}}
    vGroup2 = {"$group": {  "_id": {  "namespace": "$_id.namespace"},  "partitionPhaseCounts": {  "$push": {  "k": "$_id.partitionPhase",  "v": "$documentCount"  }  },  "totalDocumentCount": { "$sum": "$documentCount" }  }  }
    vAddFields1 = {"$addFields": {"namespace": "$_id.namespace"}}
    vProject1 = {"$project": {  "_id": 0,"namespace": 1,"totalDocumentCount": 1,  "partitionPhaseCounts":{"$arrayToObject": "$partitionPhaseCounts" }}  }
    vProject2 = {"$project": {  "_id": 0,"namespace": 1,"totalDocumentCount": 1,  "partitionPhaseCounts": {  "$mergeObjects": [  { "not started": 0, "in progress": 0, "done": 0 },  "$partitionPhaseCounts"  ]  }}  }
    vAddFields2 = {"$addFields": {"PercCompleted": {"$divide": [{ "$multiply": ["$partitionPhaseCounts.done", 100] }, "$totalDocumentCount"]}}}
    vSort1 = {"$sort": {"PercCompleted": 1, "namespace": 1}}  
    vPartitionData = internalDbDst.partitions.aggregate([vGroup1, vGroup2, vAddFields1, vProject1, vProject2, vAddFields2, vSort1])

    vPartitionData = list(vPartitionData)

    # Limits the total of namespaces to MAX_PARTITIONS_DISPLAY in the partitions completed
    if len(vPartitionData) > MAX_PARTITIONS_DISPLAY:  
        # Remove PercCompleted == 100  
        filtered = [doc for doc in vPartitionData if doc.get('PercCompleted') != 100]  
        # If we still have more than MAX_PARTITIONS_DISPLAY, trim to MAX_PARTITIONS_DISPLAY  
        if len(filtered) >= MAX_PARTITIONS_DISPLAY:  
            vPartitionData = filtered[:MAX_PARTITIONS_DISPLAY-1]  
        else:  
            # If after removal less than MAX_PARTITIONS_DISPLAY, fill up with remaining PercCompleted==100  
            needed = MAX_PARTITIONS_DISPLAY - len(filtered)  
            completed_100 = [doc for doc in vPartitionData if doc.get('PercCompleted') == 100]  
            vPartitionData = filtered + completed_100[:needed]  

    if len(vPartitionData) == 0:
        fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', textfont=dict(size=30, color="black")), row=1, col=1)
        fig.update_layout(xaxis1=dict(showgrid=False, zeroline=False, showticklabels=False), 
                          yaxis1=dict(showgrid=False, zeroline=False, showticklabels=False))
    else:
        vNamespace = []
        vPercComplete = []        
        for partition in vPartitionData:
            vNamespace.append(partition["namespace"])
            vPercComplete.append(partition["PercCompleted"])
        fig.add_trace(go.Bar(x=vPercComplete, y=vNamespace, orientation='h', 
                             marker=dict(color=vPercComplete, colorscale='blugrn')), row=1, col=1)
        fig.update_xaxes(title_text="Completed %", row=1, col=1)
        fig.update_yaxes(title_text="Namespace", row=1, col=1)
        fig.update_layout(xaxis1=dict(range=[1, 100], dtick=5))

    # 2. Total X Copied Data (Row 1, Col 2)
    vGroup = {"$group":{"_id": None, "totalCopiedBytes": { "$sum": "$copiedByteCount" }, "totalBytesCount": { "$sum": "$totalByteCount" }  }}
    vCompleteData = internalDbDst.partitions.aggregate([vGroup])
    vCompleteData = list(vCompleteData)
    vCopiedBytes = 0
    vTotalBytes = 0
    vTypeByte = ['Copied Data', 'Total Data']
    vBytes = []
    if len(vCompleteData) == 0:
        fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', textfont=dict(size=30, color="black")), row=1, col=2)
        fig.update_layout(xaxis2=dict(showgrid=False, zeroline=False, showticklabels=False), 
                          yaxis2=dict(showgrid=False, zeroline=False, showticklabels=False))
    else:        
        for comp in list(vCompleteData):
            vCopiedBytes = comp["totalCopiedBytes"] + vCopiedBytes
            vTotalBytes = comp["totalBytesCount"] + vTotalBytes
        vTotalBytes, estimated_total_bytes_unit = format_byte_size(vTotalBytes)
        vCopiedBytes = convert_bytes(vCopiedBytes, estimated_total_bytes_unit)
        vBytes.append(vCopiedBytes)
        vBytes.append(vTotalBytes)
        fig.add_trace(go.Bar(x=vBytes, y=vTypeByte, orientation='h',
                             marker=dict(color=vBytes, colorscale='redor')), row=1, col=2)
        fig.update_xaxes(title_text=f"Data in {estimated_total_bytes_unit}", row=1, col=2)
        fig.update_yaxes(title_text="Copied / Total Data", row=1, col=2)
        fig.update_layout(xaxis2=dict(range=[0, vTotalBytes]))

    # 3. Mongosync Phases (Row 2, Col 1)
    vPhase = []
    vTs = []
    if len(phaseTransitions) == 0:
        fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', textfont=dict(size=30, color="black")), row=2, col=1)
        fig.update_layout(xaxis3=dict(showgrid=False, zeroline=False, showticklabels=False), 
                          yaxis3=dict(showgrid=False, zeroline=False, showticklabels=False))
    else:        
        for pt in phaseTransitions:
            vPhase.append(pt.get("phase", "").capitalize())
            ts = pt.get("ts")
            if isinstance(ts, Timestamp):
                vTs.append(datetime.fromtimestamp(ts.time, tz=timezone.utc))
            elif isinstance(ts, datetime):
                vTs.append(ts)
            else:
                vTs.append(None)
        fig.add_trace(go.Scatter(x=vTs, y=vPhase, mode='markers+text', marker=dict(color='green')), row=2, col=1)
    
    # 4. Collections Progress (Row 2, Col 2)
    vProject1 = {"$project": {  "namespace": {  "$concat": ["$namespace.db", ".", "$namespace.coll"]  },  "partitionPhase": 1  }}
    vGroup1 = {"$group": {  "_id": "$namespace",  "phases": { "$addToSet": "$partitionPhase" }  } }
    vProject2 = {"$project": {  "_id": 0,  "namespace": "$_id",  "phases": {  "$arrayToObject": {  "$map": {  "input": "$phases",  "as": "phase",  "in": { "k": "$$phase", "v": 1 }  }  }  }  }}
    vProject3 = {"$project": {  "_id": 0,"namespace": 1,  "phases": {  "$mergeObjects": [  { "not started": 0, "in progress": 0, "done": 0 },  "$phases"  ]  }}  }

    vCollectionData = internalDbDst.partitions.aggregate([vProject1, vGroup1, vProject2, vProject3])
    vCollectionData = list(vCollectionData)

    vTypeProc = []
    vTypeValue = []
    if len(vCollectionData) == 0:
        fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', textfont=dict(size=30, color="black")), row=2, col=2)
        fig.update_layout(xaxis4=dict(showgrid=False, zeroline=False, showticklabels=False), 
                          yaxis4=dict(showgrid=False, zeroline=False, showticklabels=False))
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
        xMax = max(vTypeValue)

        fig.add_trace(go.Bar(x=vTypeValue, y=vTypeProc, orientation='h',
                             marker=dict(color=vTypeValue, colorscale='Oryel')), row=2, col=2)
        fig.update_xaxes(title_text="Totals", row=2, col=2)
        fig.update_yaxes(title_text="Process", row=2, col=2)
        fig.update_layout(xaxis4=dict(range=[0, xMax])) 
    
    # Update layout
    fig.update_layout(
        height=900,
        width=1550,
        autosize=True,
        title_text="Mongosync Progress - Timezone info: UTC",
        showlegend=False,
        plot_bgcolor="white"
    )
    
    plot_json = json.dumps(fig, cls=PlotlyJSONEncoder)
    return plot_json


def gatherEndpointMetrics(endpoint_url):
    """Fetch and display data from the Mongosync Progress Endpoint URL."""
    logger = logging.getLogger(__name__)
    
    # Create a figure for displaying endpoint data
    fig = make_subplots(
        rows=3,
        cols=4,
        row_heights=[0.35, 0.35, 0.30],
        subplot_titles=(
            "State", "Can Commit", "Can Write", "Lag Time (seconds)",
            "Mongosync ID", "Coordinator ID", "Info", "Success",
            "Collection Copy", "Direction Mapping", "Source", "Destination"
        ),
        specs=[
            [{}, {}, {}, {}],
            [{}, {}, {}, {}],
            [{}, {}, {}, {}]
        ],
        horizontal_spacing=0.08,
        vertical_spacing=0.15
    )
    
    try:
        # Make HTTP GET request to the endpoint
        url = f"http://{endpoint_url}"
        logger.info(f"Fetching data from endpoint: {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Extract progress data
        progress = data.get("progress", {})
        success = data.get("success", False)
        
        # Helper function to format values for display
        def format_value(value):
            if value is None:
                return "null"
            elif isinstance(value, bool):
                return str(value).lower()
            elif isinstance(value, dict):
                return json.dumps(value, indent=2)[:100] + "..." if len(json.dumps(value)) > 100 else json.dumps(value)
            else:
                return str(value)
        
        # Helper function to get color based on value
        def get_color(key, value):
            if key == "state":
                if value == "RUNNING":
                    return "blue"
                elif value == "IDLE":
                    return "orange"
                elif value == "COMMITTED":
                    return "green"
                elif value == "PAUSED":
                    return "red"
            elif key in ["canCommit", "canWrite", "success"]:
                return "green" if value else "gray"
            return "black"
        
        # Row 1: State, Can Commit, Can Write, Lag Time
        state = progress.get("state", "N/A")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(state)], mode='text',
                                  textfont=dict(size=20, color=get_color("state", state))), row=1, col=1)
        
        canCommit = progress.get("canCommit", False)
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(canCommit)], mode='text',
                                  textfont=dict(size=20, color=get_color("canCommit", canCommit))), row=1, col=2)
        
        canWrite = progress.get("canWrite", False)
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(canWrite)], mode='text',
                                  textfont=dict(size=20, color=get_color("canWrite", canWrite))), row=1, col=3)
        
        lagTime = progress.get("lagTimeSeconds")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(lagTime)], mode='text',
                                  textfont=dict(size=20, color="black")), row=1, col=4)
        
        # Row 2: Mongosync ID, Coordinator ID, Info, Success
        mongosyncID = progress.get("mongosyncID", "N/A")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(mongosyncID)], mode='text',
                                  textfont=dict(size=16, color="black")), row=2, col=1)
        
        coordinatorID = progress.get("coordinatorID", "N/A")
        coordText = format_value(coordinatorID) if coordinatorID else "(empty)"
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[coordText], mode='text',
                                  textfont=dict(size=16, color="black")), row=2, col=2)
        
        info = progress.get("info")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(info)], mode='text',
                                  textfont=dict(size=16, color="black")), row=2, col=3)
        
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(success)], mode='text',
                                  textfont=dict(size=20, color=get_color("success", success))), row=2, col=4)
        
        # Row 3: Collection Copy, Direction Mapping, Source, Destination
        collectionCopy = progress.get("collectionCopy")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(collectionCopy)], mode='text',
                                  textfont=dict(size=14, color="black")), row=3, col=1)
        
        directionMapping = progress.get("directionMapping")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(directionMapping)], mode='text',
                                  textfont=dict(size=14, color="black")), row=3, col=2)
        
        source = progress.get("source")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(source)], mode='text',
                                  textfont=dict(size=14, color="black")), row=3, col=3)
        
        destination = progress.get("destination")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(destination)], mode='text',
                                  textfont=dict(size=14, color="black")), row=3, col=4)
        
    except requests.exceptions.Timeout:
        logger.error(f"Timeout connecting to endpoint: {endpoint_url}")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=["TIMEOUT - Could not reach endpoint"], mode='text',
                                  textfont=dict(size=20, color="red")), row=1, col=1)
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error to endpoint {endpoint_url}: {e}")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=["CONNECTION ERROR"], mode='text',
                                  textfont=dict(size=20, color="red")), row=1, col=1)
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error to endpoint {endpoint_url}: {e}")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=["REQUEST ERROR"], mode='text',
                                  textfont=dict(size=20, color="red")), row=1, col=1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON response from endpoint {endpoint_url}: {e}")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=["INVALID JSON RESPONSE"], mode='text',
                                  textfont=dict(size=20, color="red")), row=1, col=1)
    except Exception as e:
        logger.error(f"Unexpected error fetching endpoint data: {e}")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[f"ERROR: {str(e)[:50]}"], mode='text',
                                  textfont=dict(size=16, color="red")), row=1, col=1)
    
    # Hide all axes
    for i in range(1, 13):
        fig.update_layout(**{
            f'xaxis{i}': dict(showgrid=False, zeroline=False, showticklabels=False),
            f'yaxis{i}': dict(showgrid=False, zeroline=False, showticklabels=False)
        })
    
    # Update layout
    fig.update_layout(
        height=600,
        width=1550,
        autosize=True,
        title_text=f"Mongosync Endpoint Data - {endpoint_url}",
        showlegend=False,
        plot_bgcolor="white"
    )
    
    plot_json = json.dumps(fig, cls=PlotlyJSONEncoder)
    return plot_json


def plotMetrics(has_connection_string=True, has_endpoint_url=False):
    """
    Render the metrics page with tab configuration.
    
    Credentials are stored in server-side session for security - 
    they are never passed to the client-side JavaScript.
    """
    # Use the centralized configuration
    from app_config import REFRESH_TIME

    refreshTime = REFRESH_TIME
    refreshTimeMs = str(int(refreshTime) * 1000)
    
    return render_template('metrics.html', 
                         refresh_time=refreshTime, 
                         refresh_time_ms=refreshTimeMs,
                         has_connection_string=has_connection_string,
                         has_endpoint_url=has_endpoint_url)