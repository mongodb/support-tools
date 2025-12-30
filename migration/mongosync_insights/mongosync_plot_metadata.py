import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from plotly.subplots import make_subplots
from flask import request, render_template
import json
import logging
import textwrap
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
    from app_config import INTERNAL_DB_NAME, MAX_PARTITIONS_DISPLAY, get_database
    
    TARGET_MONGO_URI = connection_string
    internalDb = INTERNAL_DB_NAME
    colors = ['red', 'blue', 'green', 'orange', 'yellow']
    
    # Connect to MongoDB cluster using connection pooling
    try:
        internalDbDst = get_database(TARGET_MONGO_URI, internalDb)
        logger.info("Connected to target MongoDB cluster using connection pooling.")
    except PyMongoError as e:
        logger.error(f"Failed to connect to target MongoDB: {e}")
        exit(1)
    # Create a subplot for the scatter plots and a separate subplot for the table
    fig = make_subplots(rows=4, 
                        cols=6, 
                        row_heights=[0.15, 0.15, 0.35, 0.35],
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

                                        "Partitions Completed %",
                                        "Total X Copied Data",

                                        "Mongosync Phases",
                                        "Collections Progress"),
                        specs=[[{}, {}, {"colspan": 2}, None, {}, {}],
                               [{}, {}, {"colspan": 2}, None, {}, {}],
                               [None, {"colspan": 2}, None, None, {"colspan": 2}, None],
                               [None, {"colspan": 2}, None, None, {"colspan": 2}, None]]                           
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

    fig.add_trace(go.Scatter(x=[0], y=[0], text=[newInitialText], mode='text', name='Mongosync Start',textfont=dict(size=17, color="black")), row=1, col=5)
    fig.update_layout(xaxis4=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis4=dict(showgrid=False, zeroline=False, showticklabels=False))
    
    #Plot Mongosync Finish time (using phaseTransitions from vResumeData)
    newFinish = get_phase_timestamp(phaseTransitions, "commit completed")
    if newFinish is None:
        newFinishText = 'NO DATA'
    else:
        newFinishText = newFinish.strftime("%Y-%m-%d %H:%M:%S")

    fig.add_trace(go.Scatter(x=[0], y=[0], text=[newFinishText], mode='text', name='Mongosync Finish',textfont=dict(size=17, color="black")), row=1, col=6)
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
    fig.add_trace(go.Scatter(x=[0], y=[0], text=[detectRandomIdValue], mode='text', name='Detect Random Id',textfont=dict(size=17, color="black")), row=2, col=5)
    fig.update_layout(xaxis9=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis9=dict(showgrid=False, zeroline=False, showticklabels=False))
    
    #Plot Verification Mode
    verificationModeValue = str(vGlobalState.get("verificationmode", "NO DATA")).capitalize() if vGlobalState else "NO DATA"
    fig.add_trace(go.Scatter(x=[0], y=[0], text=[verificationModeValue], mode='text', name='Embedded Verifier',textfont=dict(size=17, color="black")), row=2, col=6)
    fig.update_layout(xaxis10=dict(showgrid=False, zeroline=False, showticklabels=False), 
                      yaxis10=dict(showgrid=False, zeroline=False, showticklabels=False))

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

    #Limits the total of namespaces to MAX_PARTITIONS_DISPLAY in the partitions completed
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
        fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', name='Mongosync Finish',textfont=dict(size=30, color="black")), row=3, col=2)
        fig.update_layout(xaxis11=dict(showgrid=False, zeroline=False, showticklabels=False), 
                          yaxis11=dict(showgrid=False, zeroline=False, showticklabels=False))
    else:
        vNamespace = []
        vPercComplete = []        
        for partition in vPartitionData:
            vNamespace.append(partition["namespace"])
            vPercComplete.append(partition["PercCompleted"])
        fig.add_trace(go.Bar(x=vPercComplete, y=vNamespace, orientation='h', 
                             marker=dict(color=vPercComplete, colorscale='blugrn')), row=3, col=2)
        fig.update_xaxes(title_text="Completed %", row=3, col=2)
        fig.update_yaxes(title_text="Namespace", row=3, col=2)
        fig.update_layout(xaxis11=dict(range=[1, 100], dtick=5))

    #Plot total and copied data
    vGroup = {"$group":{"_id": None, "totalCopiedBytes": { "$sum": "$copiedByteCount" }, "totalBytesCount": { "$sum": "$totalByteCount" }  }}
    vCompleteData = internalDbDst.partitions.aggregate([vGroup])
    vCompleteData=list(vCompleteData)
    vCopiedBytes=0
    vTotalBytes=0
    vTypeByte=['Copied Data', 'Total Data']
    vBytes=[]
    if len(vCompleteData) == 0:
        fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', textfont=dict(size=30, color="black")), row=3, col=5)
        fig.update_layout(xaxis12=dict(showgrid=False, zeroline=False, showticklabels=False), 
                          yaxis12=dict(showgrid=False, zeroline=False, showticklabels=False))
    else:        
        for comp in list(vCompleteData):
            vCopiedBytes=comp["totalCopiedBytes"] + vCopiedBytes
            vTotalBytes=comp["totalBytesCount"] + vTotalBytes
        vTotalBytes, estimated_total_bytes_unit = format_byte_size(vTotalBytes)
        vCopiedBytes = convert_bytes(vCopiedBytes, estimated_total_bytes_unit)
        vBytes.append(vCopiedBytes)
        vBytes.append(vTotalBytes)
        fig.add_trace(go.Bar(x=vBytes, y=vTypeByte, orientation='h',
                             marker=dict(color=vBytes, colorscale='redor')), row=3, col=5)
        fig.update_xaxes(title_text=f"Data in {estimated_total_bytes_unit}", row=3, col=5)
        fig.update_yaxes(title_text="Copied / Total Data", row=3, col=5)
        fig.update_layout(xaxis12=dict(range=[0, vTotalBytes]))

    #Plot Phases transitions (using phaseTransitions from vResumeData)
    vPhase=[]
    vTs=[]
    if len(phaseTransitions) == 0:
        fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', textfont=dict(size=30, color="black")), row=4, col=2)
        fig.update_layout(xaxis13=dict(showgrid=False, zeroline=False, showticklabels=False), 
                          yaxis13=dict(showgrid=False, zeroline=False, showticklabels=False))
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
        fig.add_trace(go.Scatter(x=vTs, y=vPhase, mode='markers+text',marker=dict(color='green')), row=4, col=2)
    
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
        fig.add_trace(go.Scatter(x=[0], y=[0], text="NO DATA", mode='text', textfont=dict(size=30, color="black")), row=4, col=5)
        fig.update_layout(xaxis14=dict(showgrid=False, zeroline=False, showticklabels=False), 
                          yaxis14=dict(showgrid=False, zeroline=False, showticklabels=False))
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
                             marker=dict(color=vTypeValue, colorscale='Oryel')), row=4, col=5)
        fig.update_xaxes(title_text=f"Totals", row=4, col=5)
        fig.update_yaxes(title_text="Process", row=4, col=5)
        fig.update_layout(xaxis14=dict(range=[0, xMax])) 
    
    # Update layout
    fig.update_layout(height=1000, width=1550, autosize=True, title_text="Mongosync Replication Progress - Timezone info: UTC", showlegend=False, plot_bgcolor="white")
    
    # Convert the figure to JSON
    plot_json = json.dumps(fig, cls=PlotlyJSONEncoder)
    return plot_json


def plotMetrics():
    # Use the centralized configuration
    from app_config import REFRESH_TIME

    refreshTime = REFRESH_TIME
    refreshTimeMs = str(int(refreshTime) * 1000)
    
    return render_template('metrics.html', 
                         refresh_time=refreshTime, 
                         refresh_time_ms=refreshTimeMs)