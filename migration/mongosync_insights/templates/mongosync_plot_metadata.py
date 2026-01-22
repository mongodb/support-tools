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
    # Create a subplot for status information (3 rows)
    fig = make_subplots(rows=3, 
                        cols=5, 
                        row_heights=[0.35, 0.35, 0.30],
                        subplot_titles=("Current State", 
                                        "Current Phase",
                                        "Lag Time",
                                        "Start",
                                        "Finish",

                                        "Reversible",
                                        "Write Blocking Mode",
                                        "Build Indexes",
                                        "Detect Random Id",
                                        "Embedded Verifier",
                                        
                                        "Namespace Filter - Inclusion",
                                        "Namespace Filter - Exclusion"),
                        specs=[[{}, {}, {}, {}, {}],
                               [{}, {}, {}, {}, {}],
                               [{"type": "table", "colspan": 2}, None, None, {"type": "table", "colspan": 2}, None]]                           
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
    
    # Helper function to format namespace filter data for table display
    def format_namespace_filter(filter_data, filter_type="inclusion"):
        """Convert namespace filter data to table columns (keys, values).
        
        Args:
            filter_data: The filter data from globalState
            filter_type: "inclusion" or "exclusion" - affects empty state message
        """
        # Handle empty/null filter data
        if not filter_data:
            if filter_type == "inclusion":
                return ["Database"], ["All (no filter)"]
            else:  # exclusion
                return ["Filter"], ["No filter"]
        
        keys = []
        values = []
        
        for idx, item in enumerate(filter_data):
            if isinstance(item, dict):
                # Extract database info
                database = item.get("database")
                if database:
                    # Flatten nested lists
                    if isinstance(database, list):
                        db_list = []
                        for db in database:
                            if isinstance(db, list):
                                db_list.extend(db)
                            else:
                                db_list.append(str(db))
                        keys.append("Database")
                        values.append(", ".join(db_list) if db_list else "All (no filter)")
                
                # Extract collections info
                collections = item.get("collections")
                if collections:
                    if isinstance(collections, list):
                        keys.append("Collections")
                        values.append(", ".join([str(c) for c in collections]))
                    else:
                        keys.append("Collections")
                        values.append(str(collections))
                elif collections is None and database:
                    keys.append("Collections")
                    values.append("All (no filter)")
        
        if not keys:
            if filter_type == "inclusion":
                return ["Database"], ["All (no filter)"]
            else:  # exclusion
                return ["Filter"], ["No filter"]
        
        return keys, values
    
    # Parse namespaceFilter from globalState
    namespaceFilter = vGlobalState.get("namespaceFilter", {}) if vGlobalState else {}
    inclusionFilter = namespaceFilter.get("inclusionFilter") if namespaceFilter else None
    exclusionFilter = namespaceFilter.get("exclusionFilter") if namespaceFilter else None
    
    # Create Inclusion Filter table
    inc_keys, inc_values = format_namespace_filter(inclusionFilter, "inclusion")
    fig.add_trace(go.Table(
        header=dict(values=["Key", "Value"], font=dict(size=12, color='black')),
        cells=dict(values=[inc_keys, inc_values], align=['left'], font=dict(size=10, color='darkblue')),
        columnwidth=[0.75, 2.5]
    ), row=3, col=1)
    
    # Create Exclusion Filter table
    exc_keys, exc_values = format_namespace_filter(exclusionFilter, "exclusion")
    fig.add_trace(go.Table(
        header=dict(values=["Key", "Value"], font=dict(size=12, color='black')),
        cells=dict(values=[exc_keys, exc_values], align=['left'], font=dict(size=10, color='darkblue')),
        columnwidth=[0.75, 2.5]
    ), row=3, col=4)
    
    # Update layout
    fig.update_layout(height=650, width=1550, autosize=True, title_text="Mongosync Status - Timezone info: UTC", showlegend=False, plot_bgcolor="white")
    
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
        rows=4,
        cols=4,
        row_heights=[0.25, 0.25, 0.25, 0.25],
        subplot_titles=(
            "State", "Lag Time", "Can Commit", "Can Write",
            "Info", "Mongosync ID", "Coordinator ID", "Collection Copy",
            "Direction Mapping", "Source", "Destination", "Events Applied",
            "Embedded Verifier Status", "Verifier Document Count"
        ),
        specs=[
            [{}, {}, {}, {}],
            [{}, {}, {}, {"type": "pie"}],
            [{"type": "table"}, {"type": "table"}, {"type": "table"}, {}],
            [{"type": "table", "colspan": 3}, None, None, {"type": "pie"}]
        ],
        horizontal_spacing=0.08,
        vertical_spacing=0.12
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
        
        # Helper function to format values for display
        def format_value(value):
            if value is None:
                return "No Data"
            elif isinstance(value, bool):
                return str(value).capitalize()
            elif isinstance(value, dict):
                json_str = json.dumps(value, indent=2)
                return (json_str[:100] + "...").capitalize() if len(json_str) > 100 else json_str.capitalize()
            else:
                str_value = str(value).strip()
                if str_value == "" or str_value.upper() in ("N/A", "NULL", "NONE"):
                    return "No Data"
                return str_value.capitalize()
        
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
            elif key in ["canCommit", "canWrite"]:
                return "green" if value else "red"
            return "black"
        
        # Helper function to format lag time in seconds to human-readable format
        def format_lag_time(seconds):
            if seconds is None:
                return "No Data"
            try:
                total_seconds = int(seconds)
                if total_seconds < 0:
                    return "0s"
                days, remainder = divmod(total_seconds, 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, secs = divmod(remainder, 60)
                parts = []
                if days > 0:
                    parts.append(f"{days}d")
                if hours > 0:
                    parts.append(f"{hours}h")
                if minutes > 0:
                    parts.append(f"{minutes}m")
                parts.append(f"{secs}s")
                return " ".join(parts)
            except (ValueError, TypeError):
                return "No Data"
        
        # Row 1: State, Lag Time, Can Commit, Can Write
        state = progress.get("state", "N/A")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(state)], mode='text',
                                  textfont=dict(size=20, color=get_color("state", state))), row=1, col=1)
        
        lagTime = progress.get("lagTimeSeconds")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_lag_time(lagTime)], mode='text',
                                  textfont=dict(size=20, color="black")), row=1, col=2)
        
        canCommit = progress.get("canCommit", False)
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(canCommit)], mode='text',
                                  textfont=dict(size=20, color=get_color("canCommit", canCommit))), row=1, col=3)
        
        canWrite = progress.get("canWrite", False)
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(canWrite)], mode='text',
                                  textfont=dict(size=20, color=get_color("canWrite", canWrite))), row=1, col=4)
        
        # Row 2: Info, Mongosync ID, Coordinator ID, Collection Copy (pie chart)
        info = progress.get("info")
        infoText = "No Data" if info is None or str(info).strip() == "" else str(info).upper()
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[infoText], mode='text',
                                  textfont=dict(size=16, color="black")), row=2, col=1)
        
        mongosyncID = progress.get("mongosyncID", "N/A")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(mongosyncID)], mode='text',
                                  textfont=dict(size=16, color="black")), row=2, col=2)
        
        coordinatorID = progress.get("coordinatorID", "N/A")
        coordText = format_value(coordinatorID) if coordinatorID else "No Data"
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[coordText], mode='text',
                                  textfont=dict(size=16, color="black")), row=2, col=3)
        
        # Collection Copy (pie chart) - Row 2, Col 4
        collectionCopy = progress.get("collectionCopy", {})
        if collectionCopy and isinstance(collectionCopy, dict):
            estimatedTotalBytes = collectionCopy.get("estimatedTotalBytes", 0) or 0
            estimatedCopiedBytes = collectionCopy.get("estimatedCopiedBytes", 0) or 0
            remainingBytes = max(0, estimatedTotalBytes - estimatedCopiedBytes)
            
            if estimatedTotalBytes > 0:
                # Format bytes to human-readable format
                copiedValue, copiedUnit = format_byte_size(estimatedCopiedBytes)
                remainingValue, remainingUnit = format_byte_size(remainingBytes)
                
                # Create labels with formatted byte sizes
                copiedLabel = f"Copied ({copiedValue:.2f} {copiedUnit})"
                remainingLabel = f"Remaining ({remainingValue:.2f} {remainingUnit})"
                
                # Create pie chart with copied vs remaining bytes
                fig.add_trace(go.Pie(
                    labels=[copiedLabel, remainingLabel],
                    values=[estimatedCopiedBytes, remainingBytes],
                    marker=dict(colors=["green", "lightgray"]),
                    textinfo="percent",
                    textposition="outside",
                    textfont=dict(size=12),
                    hole=0.3,
                    showlegend=True
                ), row=2, col=4)
            else:
                fig.add_trace(go.Pie(
                    labels=["No Data"],
                    values=[1],
                    marker=dict(colors=["lightgray"]),
                    textinfo="label",
                    textfont=dict(size=14),
                    showlegend=False
                ), row=2, col=4)
        else:
            fig.add_trace(go.Pie(
                labels=["No Data"],
                values=[1],
                marker=dict(colors=["lightgray"]),
                textinfo="label",
                textfont=dict(size=14),
                showlegend=False
            ), row=2, col=4)
        
        # Helper function to create table data from dict
        def dict_to_table(data):
            if not data or not isinstance(data, dict):
                return ["Key"], ["No Data"]
            keys = []
            values = []
            for k, v in data.items():
                # Wrap long values
                key_str = str(k).capitalize()
                val_str = str(v) if v is not None else "No Data"
                # Wrap text if longer than 30 characters
                if len(val_str) > 30:
                    val_str = "<br>".join([val_str[i:i+30] for i in range(0, len(val_str), 30)])
                keys.append(key_str)
                values.append(val_str)
            return keys, values
        
        # Row 3: Direction Mapping, Source, Destination, Events Applied
        directionMapping = progress.get("directionMapping")
        dm_keys, dm_values = dict_to_table(directionMapping)
        fig.add_trace(go.Table(
            header=dict(values=["Key", "Value"], font=dict(size=12, color='black')),
            cells=dict(values=[dm_keys, dm_values], align=['left'], font=dict(size=10, color='darkblue')),
            columnwidth=[0.75, 2.5]
        ), row=3, col=1)
        
        source = progress.get("source")
        src_keys, src_values = dict_to_table(source)
        fig.add_trace(go.Table(
            header=dict(values=["Key", "Value"], font=dict(size=12, color='black')),
            cells=dict(values=[src_keys, src_values], align=['left'], font=dict(size=10, color='darkblue')),
            columnwidth=[0.75, 2.5]
        ), row=3, col=2)
        
        destination = progress.get("destination")
        dst_keys, dst_values = dict_to_table(destination)
        fig.add_trace(go.Table(
            header=dict(values=["Key", "Value"], font=dict(size=12, color='black')),
            cells=dict(values=[dst_keys, dst_values], align=['left'], font=dict(size=10, color='darkblue')),
            columnwidth=[0.75, 2.5]
        ), row=3, col=3)
        
        totalEventsApplied = progress.get("totalEventsApplied")
        fig.add_trace(go.Scatter(x=[0], y=[0], text=[format_value(totalEventsApplied)], mode='text',
                                  textfont=dict(size=14, color="black")), row=3, col=4)
        
        # Row 4: Verification comparison table (source vs destination)
        verification = progress.get("verification", {})
        verif_source = verification.get("source", {}) if verification else {}
        verif_dest = verification.get("destination", {}) if verification else {}
        
        # Define the fields to compare
        verif_fields = [
            ("phase", "Phase"),
            ("lagTimeSeconds", "Lag Time Seconds"), 
            ("totalCollectionCount", "Total Collection Count"),
            ("scannedCollectionCount", "Scanned Collection Count"),
            ("hashedDocumentCount", "Hashed Document Count"),
            ("estimatedDocumentCount", "Estimated Document Count")
        ]
        
        # Build table columns
        field_names = []
        source_values = []
        dest_values = []
        
        for field_key, field_label in verif_fields:
            field_names.append(field_label)
            
            # Get source value
            src_val = verif_source.get(field_key) if verif_source else None
            source_values.append(str(src_val) if src_val is not None else "No Data")
            
            # Get destination value
            dst_val = verif_dest.get(field_key) if verif_dest else None
            dest_values.append(str(dst_val) if dst_val is not None else "No Data")
        
        # Create verification comparison table
        if verification:
            fig.add_trace(go.Table(
                header=dict(values=["Field", "Source", "Destination"], font=dict(size=12, color='black')),
                cells=dict(values=[field_names, source_values, dest_values], align=['left'], font=dict(size=10, color='darkblue')),
                columnwidth=[1.5, 1, 1]
            ), row=4, col=1)
        else:
            fig.add_trace(go.Table(
                header=dict(values=["Field", "Source", "Destination"], font=dict(size=12, color='black')),
                cells=dict(values=[["Verification"], ["No Data"], ["No Data"]], align=['left'], font=dict(size=10, color='darkblue')),
                columnwidth=[1.5, 1, 1]
            ), row=4, col=1)
        
        # Verifier Document Count pie chart (Verified vs Remaining)
        src_estimated_docs = verif_source.get("estimatedDocumentCount", 0) or 0 if verif_source else 0
        dst_estimated_docs = verif_dest.get("estimatedDocumentCount", 0) or 0 if verif_dest else 0
        
        # Verified Documents = src_estimated_docs (documents already verified)
        # Remaining Documents = dst_estimated_docs - src_estimated_docs (documents left to verify)
        verified_docs = dst_estimated_docs
        remaining_docs = max(0,  src_estimated_docs - dst_estimated_docs)
        
        if verified_docs > 0 or remaining_docs > 0:
            fig.add_trace(go.Pie(
                labels=[f"Verified ({verified_docs:,})", f"Remaining ({remaining_docs:,})"],
                values=[verified_docs, remaining_docs],
                marker=dict(colors=["green", "lightgray"]),
                textinfo="percent",
                textposition="outside",
                textfont=dict(size=12),
                hole=0.3,
                showlegend=True
            ), row=4, col=4)
        else:
            fig.add_trace(go.Pie(
                labels=["No Data"],
                values=[1],
                marker=dict(colors=["lightgray"]),
                textinfo="label",
                textfont=dict(size=14),
                showlegend=False
            ), row=4, col=4)
        
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
    
    # Hide all axes (4 rows x 4 cols = 16 potential axes)
    for i in range(1, 17):
        fig.update_layout(**{
            f'xaxis{i}': dict(showgrid=False, zeroline=False, showticklabels=False),
            f'yaxis{i}': dict(showgrid=False, zeroline=False, showticklabels=False)
        })
    
    # Update layout
    fig.update_layout(
        height=800,
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