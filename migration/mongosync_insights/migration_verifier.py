"""
Migration Verifier metrics gathering and visualization.
Provides monitoring for MongoDB migration-verifier tool.
https://github.com/mongodb-labs/migration-verifier
"""
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from plotly.subplots import make_subplots
from flask import render_template
import json
import logging
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)


def get_latest_generation(db):
    """Get the latest generation number from verification_tasks."""
    pipeline = [
        {"$sort": {"generation": -1}},
        {"$limit": 1},
        {"$project": {"generation": 1, "_id": 0}}
    ]
    result = list(db.verification_tasks.aggregate(pipeline))
    if result:
        return result[0].get("generation", 0)
    return 0


def get_verification_summary(db, generation):
    """Get summary of verification tasks for a generation."""
    pipeline = [
        {"$match": {"generation": generation}},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1}
        }}
    ]
    results = list(db.verification_tasks.aggregate(pipeline))
    summary = {
        "completed": 0,
        "failed": 0,
        "mismatch": 0,
        "pending": 0,
        "processing": 0
    }
    for r in results:
        status = r["_id"]
        if status in summary:
            summary[status] = r["count"]
        elif status == "added":
            summary["pending"] += r["count"]
    return summary


def get_task_type_distribution(db, generation):
    """Get distribution of task types for a generation."""
    pipeline = [
        {"$match": {"generation": generation}},
        {"$group": {
            "_id": "$type",
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}}
    ]
    return list(db.verification_tasks.aggregate(pipeline))


def get_failed_tasks(db, generation, limit=50):
    """Get failed verification tasks with details including mismatch info."""
    # First get basic task info (fast query)
    pipeline = [
        {"$match": {"generation": generation, "status": {"$in": ["failed", "mismatch"]}}},
        {"$sort": {"begin_time": -1}},
        {"$limit": limit},
        {"$project": {
            "_id": 1,
            "type": 1,
            "status": 1,
            "query_filter": 1,
            "_ids": 1,
            "failed_docs": 1,
            "begin_time": 1
        }}
    ]
    tasks = list(db.verification_tasks.aggregate(pipeline))
    
    # For first 20 tasks, try to get mismatch details (separate fast query)
    if tasks:
        task_ids = [t["_id"] for t in tasks[:20]]
        try:
            mismatches = list(db.mismatches.find(
                {"task": {"$in": task_ids}},
                {"task": 1, "detail": 1}
            ).limit(20))
            
            # Create lookup dict
            mismatch_map = {m["task"]: m for m in mismatches}
            
            # Attach mismatch info to tasks
            for t in tasks:
                if t["_id"] in mismatch_map:
                    t["mismatch"] = mismatch_map[t["_id"]]
        except Exception:
            pass  # Skip mismatch lookup if it fails
    
    return tasks


def get_mismatches_with_details(db, generation, limit=100):
    """Get verification tasks joined with mismatch details."""
    pipeline = [
        {"$match": {"generation": generation, "status": {"$in": ["failed", "mismatch"]}}},
        {
            "$lookup": {
                "from": "mismatches",
                "localField": "_id",
                "foreignField": "task",
                "as": "mismatch"
            }
        },
        {"$unwind": {"path": "$mismatch", "preserveNullAndEmptyArrays": True}},
        {"$limit": limit}
    ]
    return list(db.verification_tasks.aggregate(pipeline))


def get_collection_mismatches(db, generation):
    """Get collection/index metadata mismatches."""
    return list(db.verification_tasks.find({
        "generation": generation,
        "status": "mismatch",
        "type": "verifyCollection"
    }))


def get_namespace_stats(db, generation):
    """Get statistics grouped by namespace for the specified generation."""
    pipeline = [
        {"$match": {"generation": generation}},
        {"$group": {
            "_id": "$query_filter.namespace",
            "total": {"$sum": 1},
            "completed": {"$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$in": ["$status", ["failed", "mismatch"]]}, 1, 0]}},
            "pending": {"$sum": {"$cond": [{"$in": ["$status", ["added", "pending"]]}, 1, 0]}}
        }},
        {"$sort": {"failed": -1, "total": -1}},
        {"$limit": 15}  # Reduced for performance
    ]
    return list(db.verification_tasks.aggregate(pipeline, allowDiskUse=True))


def get_generation_history(db, limit=4):
    """Get history of latest generations with their stats - optimized for performance."""
    # First, quickly find the latest generation numbers
    latest_gen_doc = db.verification_tasks.find_one(
        {},
        {"generation": 1},
        sort=[("generation", -1)]
    )
    
    if not latest_gen_doc:
        return []
    
    latest_gen = latest_gen_doc.get("generation", 0)
    
    # Only aggregate for the latest N generations (much faster)
    gen_range = list(range(max(0, latest_gen - limit + 1), latest_gen + 1))
    
    pipeline = [
        {"$match": {"generation": {"$in": gen_range}}},  # Filter first for speed
        {"$group": {
            "_id": "$generation",
            "total_tasks": {"$sum": 1},
            "completed": {"$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$in": ["$status", ["failed", "mismatch"]]}, 1, 0]}},
            "first_task_time": {"$min": "$begin_time"}
        }},
        {"$sort": {"_id": -1}},
        {"$limit": limit}
    ]
    return list(db.verification_tasks.aggregate(pipeline, allowDiskUse=True))


def get_generation_name(gen_num):
    """Get human-readable name for a generation."""
    if gen_num is None:
        return "Unknown"
    elif gen_num == 0:
        return "Initial Verification"
    else:
        return f"Recheck #{gen_num}"


def gatherVerifierMetrics(connection_string, db_name="migration_verification_metadata"):
    """Gather all verifier metrics and create Plotly figure."""
    from app_config import get_database
    
    try:
        db = get_database(connection_string, db_name)
        logger.info(f"Connected to verifier database: {db_name}")
    except PyMongoError as e:
        logger.error(f"Failed to connect to verifier database: {e}")
        return json.dumps({"error": str(e)})
    except Exception as e:
        logger.error(f"Unexpected error connecting to verifier database: {e}")
        return json.dumps({"error": f"Connection error: {str(e)}"})

    try:
        # Get latest generations history (limited for performance)
        gen_history = get_generation_history(db, limit=4)
        
        # Get the generations we want to show (latest and any with failures)
        generations_to_show = []
        for g in gen_history:
            gen_num = g["_id"]
            if gen_num is not None:
                generations_to_show.append({
                    "num": gen_num,
                    "name": get_generation_name(gen_num),
                    "total": g["total_tasks"],
                    "completed": g["completed"],
                    "failed": g["failed"],
                    "start_time": g.get("first_task_time", "N/A")
                })
        
        # Sort by generation number DESCENDING (latest first)
        generations_to_show.sort(key=lambda x: x["num"] if x["num"] is not None else -1, reverse=True)
        
        # Find the LAST generation (the only one that matters for final result)
        last_gen_num = max([g["num"] for g in generations_to_show]) if generations_to_show else 0
        
        # Mark which is the last generation
        for g in generations_to_show:
            g["is_last"] = (g["num"] == last_gen_num)
            if g["is_last"]:
                g["name"] = f"★ {g['name']} (FINAL)"
        
        # Limit to latest 4 generations for display
        generations_to_show = generations_to_show[:4]
        
        # Get namespace stats - always use all-time stats for comprehensive view
        try:
            all_ns_pipeline = [
                {"$group": {
                    "_id": "$query_filter.namespace",
                    "total": {"$sum": 1},
                    "completed": {"$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}},
                    "failed": {"$sum": {"$cond": [{"$in": ["$status", ["failed", "mismatch"]]}, 1, 0]}},
                    "pending": {"$sum": {"$cond": [{"$in": ["$status", ["added", "pending", "processing"]]}, 1, 0]}}
                }},
                {"$sort": {"failed": -1, "total": -1}},
                {"$limit": 25}
            ]
            namespace_stats = list(db.verification_tasks.aggregate(all_ns_pipeline, maxTimeMS=60000))
        except Exception as e:
            logger.warning(f"Failed to get all-time namespace stats: {e}")
            # Fallback to last generation only
            namespace_stats = get_namespace_stats(db, last_gen_num)
        
        # Get collection mismatches - focus on LAST generation (the only one that matters)
        # Per docs: "the only failures we care about are in the last generation"
        all_collection_mismatches = list(db.verification_tasks.find({
            "generation": last_gen_num,
            "status": "mismatch",
            "type": "verifyCollection"
        }).limit(100))

        # Calculate number of rows: 1 overview + generations + 1 namespace + 1 collection mismatches
        num_gens = len(generations_to_show)
        total_rows = 1 + num_gens + 1 + 1
        
        # Build specs
        specs = [
            [{"colspan": 2, "type": "table"}, None],  # Row 1: Overview (full width)
        ]
        for _ in generations_to_show:
            specs.append([{"type": "domain"}, {"type": "table"}])  # Each gen: pie + failed table
        specs.append([{"colspan": 2}, None])  # Namespace progress bar chart
        specs.append([{"colspan": 2, "type": "table"}, None])  # Collection mismatches
        
        # Row heights - give more space to overview and generation rows
        row_heights = [0.18] + [0.22] * num_gens + [0.20, 0.12]
        
        # Create subplot figure
        fig = make_subplots(
            rows=total_rows, cols=2,
            specs=specs,
            row_heights=row_heights,
            column_widths=[0.35, 0.65],
            horizontal_spacing=0.05,
            vertical_spacing=0.06
        )
        
        current_row = 1

        # Row 1: Overview table showing all generations
        if generations_to_show:
            overview_headers = ['Generation', 'Name', 'Total Tasks', 'Completed', 'Failed', 'Start Time']
            overview_values = [
                [str(g["num"]) for g in generations_to_show],
                [g["name"] for g in generations_to_show],
                [str(g["total"]) for g in generations_to_show],
                [str(g["completed"]) for g in generations_to_show],
                [str(g["failed"]) for g in generations_to_show],
                [str(g["start_time"])[:16] if g["start_time"] != "N/A" else "N/A" for g in generations_to_show]
            ]
            # Color rows based on failures
            row_colors = []
            for g in generations_to_show:
                if g["failed"] > 0:
                    row_colors.append('#fdeaea')
                elif g["completed"] == g["total"] and g["total"] > 0:
                    row_colors.append('#e8f8e8')
                else:
                    row_colors.append('#f0f8ff')
            
            fig.add_trace(
                go.Table(
                    columnwidth=[100, 220, 120, 120, 100, 180],  # Even wider columns
                    header=dict(
                        values=overview_headers,
                        fill_color='#2c3e50',
                        font=dict(color='white', size=18),
                        align='center',
                        height=50
                    ),
                    cells=dict(
                        values=overview_values,
                        fill_color=[row_colors],
                        font=dict(size=17),
                        align='center',
                        height=45
                    )
                ),
                row=1, col=1
            )
        
        current_row = 2
        
        # Rows for each generation
        for gen in generations_to_show:
            gen_num = gen["num"]
            gen_name = gen["name"]
            
            # Get summary for this generation
            gen_summary = get_verification_summary(db, gen_num)
            completed = gen_summary.get("completed", 0)
            failed = gen_summary.get("failed", 0) + gen_summary.get("mismatch", 0)
            pending = gen_summary.get("pending", 0) + gen_summary.get("processing", 0)
            
            # Pie chart for this generation
            pie_labels = []
            pie_values = []
            pie_colors = []
            if completed > 0:
                pie_labels.append(f"Completed ({completed})")
                pie_values.append(completed)
                pie_colors.append("#2ecc71")
            if failed > 0:
                pie_labels.append(f"Failed ({failed})")
                pie_values.append(failed)
                pie_colors.append("#e74c3c")
            if pending > 0:
                pie_labels.append(f"Pending ({pending})")
                pie_values.append(pending)
                pie_colors.append("#3498db")
            
            if not pie_values:
                pie_labels = ["No Tasks"]
                pie_values = [1]
                pie_colors = ["#95a5a6"]
            
            fig.add_trace(
                go.Pie(
                    labels=pie_labels,
                    values=pie_values,
                    marker=dict(colors=pie_colors),
                    textinfo='label+percent',
                    textfont=dict(size=16),
                    hole=0.35,
                    showlegend=False,
                    title=dict(
                        text=f"<b>{gen_name}</b>",
                        font=dict(size=18, color="#2c3e50"),
                        position="top center"
                    )
                ),
                row=current_row, col=1
            )
            
            # Failed tasks table for this generation - show up to 100 failed tasks (limited for performance)
            gen_failed_tasks = get_failed_tasks(db, gen_num, limit=100)
            if gen_failed_tasks:
                failed_headers = ['Type', 'Source NS', 'Dest NS', 'Mismatch Details']
                
                # Build detailed mismatch description based on task type
                def get_mismatch_details(t):
                    task_type = t.get("type", "")
                    
                    if task_type == "verifyCollection":
                        # Collection/Index metadata mismatches - check mismatch.detail first
                        mismatch = t.get("mismatch", {})
                        if mismatch and isinstance(mismatch, dict):
                            detail = mismatch.get("detail", {})
                            if detail:
                                idx_id = detail.get("id", "?")
                                field_type = detail.get("field", "")
                                details_str = detail.get("details", "")
                                cluster = detail.get("cluster", "")
                                
                                # Extract key info from details string
                                if "unique" in details_str.lower():
                                    if "src:" in details_str and "unique\": true" in details_str:
                                        if "dst:" in details_str and "unique" not in details_str.split("dst:")[1][:50]:
                                            return f"Index '{idx_id}' ({field_type}): unique constraint missing on {cluster}"
                                    return f"Index '{idx_id}' ({field_type}): Mismatch on {cluster}"
                                elif "Missing" in details_str:
                                    return f"Index '{idx_id}' ({field_type}): Missing on {cluster}"
                                else:
                                    return f"Index '{idx_id}' ({field_type}): {details_str[:60]}... ({cluster})"
                        
                        # Fallback to failed_docs
                        failed_docs = t.get("failed_docs", [])
                        if failed_docs:
                            details = []
                            for fd in failed_docs[:3]:
                                idx_id = fd.get("id", "?")
                                idx_details = fd.get("details", "")
                                cluster = fd.get("cluster", "")
                                if idx_details:
                                    details.append(f"{idx_id}: {idx_details[:30]} ({cluster})")
                                else:
                                    details.append(f"{idx_id} ({cluster})")
                            result = "; ".join(details)
                            if len(failed_docs) > 3:
                                result += f"... +{len(failed_docs)-3} more"
                            return result
                        return "Metadata mismatch (no details)"
                    
                    elif task_type in ["verify", "verifyDocuments"]:
                        # Document mismatches - check mismatch.detail first
                        mismatch = t.get("mismatch", {})
                        if mismatch and isinstance(mismatch, dict):
                            detail = mismatch.get("detail", {})
                            if detail:
                                doc_id = detail.get("id", "?")
                                field = detail.get("field", "")
                                details_str = detail.get("details", "")
                                cluster = detail.get("cluster", "")
                                if field:
                                    return f"Doc '{doc_id}', field '{field}': {details_str[:40]}... ({cluster})"
                                return f"Doc '{doc_id}': {details_str[:50]}... ({cluster})"
                        
                        # Fallback to _ids
                        ids = t.get("_ids", [])
                        if ids:
                            count = len(ids)
                            sample = ", ".join([str(i)[:20] for i in ids[:5]])
                            if count > 5:
                                return f"{count} docs mismatched: {sample}..."
                            return f"{count} docs: {sample}"
                        return "Document mismatch (no details)"
                    
                    else:
                        # Other task types
                        mismatch = t.get("mismatch", {})
                        if mismatch and isinstance(mismatch, dict):
                            detail = mismatch.get("detail", {})
                            if detail:
                                return f"{detail.get('id', '?')}: {detail.get('details', 'N/A')[:50]}..."
                        if t.get("_ids"):
                            return f"{len(t.get('_ids', []))} items"
                        elif t.get("failed_docs"):
                            return f"{len(t.get('failed_docs', []))} issues"
                        return t.get("status", "N/A")
                
                # Extract namespace info
                def get_source_ns(t):
                    qf = t.get("query_filter", {})
                    return qf.get("namespace", "N/A") or "N/A"
                
                def get_dest_ns(t):
                    qf = t.get("query_filter", {})
                    return qf.get("to", qf.get("namespace", "N/A")) or "N/A"
                
                failed_values = [
                    [t.get("type", "N/A") for t in gen_failed_tasks],
                    [get_source_ns(t) for t in gen_failed_tasks],
                    [get_dest_ns(t) for t in gen_failed_tasks],
                    [get_mismatch_details(t) for t in gen_failed_tasks]
                ]
                fig.add_trace(
                    go.Table(
                        columnwidth=[120, 200, 200, 350],  # Wider columns for details
                        header=dict(
                            values=failed_headers,
                            fill_color='#c0392b',
                            font=dict(color='white', size=13),
                            align='center',
                            height=32
                        ),
                        cells=dict(
                            values=failed_values,
                            fill_color='#fdf2f2',
                            font=dict(size=11),
                            align='left',
                            height=30
                        )
                    ),
                    row=current_row, col=2
                )
            else:
                fig.add_trace(
                    go.Table(
                        header=dict(
                            values=[f'✓ {gen_name}'],
                            fill_color='#27ae60',
                            font=dict(color='white', size=14),
                            height=32
                        ),
                        cells=dict(
                            values=[['No failed or mismatched tasks']],
                            fill_color='#d5f5e3',
                            font=dict(size=14, color='#27ae60'),
                            height=35
                        )
                    ),
                    row=current_row, col=2
                )
            
            current_row += 1

        # Namespace progress bar chart
        max_namespaces = min(25, len(namespace_stats)) if namespace_stats else 0
        if namespace_stats and max_namespaces > 0:
            ns_labels = [ns["_id"] or "unknown" for ns in namespace_stats[:max_namespaces]]
            ns_completed = [ns["completed"] for ns in namespace_stats[:max_namespaces]]
            ns_failed = [ns["failed"] for ns in namespace_stats[:max_namespaces]]
            ns_pending = [ns["pending"] for ns in namespace_stats[:max_namespaces]]
            
            fig.add_trace(
                go.Bar(name='Completed', x=ns_completed, y=ns_labels, orientation='h', 
                       marker=dict(color='#2ecc71'), showlegend=True),
                row=current_row, col=1
            )
            fig.add_trace(
                go.Bar(name='Failed', x=ns_failed, y=ns_labels, orientation='h', 
                       marker=dict(color='#e74c3c'), showlegend=True),
                row=current_row, col=1
            )
            fig.add_trace(
                go.Bar(name='Pending', x=ns_pending, y=ns_labels, orientation='h', 
                       marker=dict(color='#3498db'), showlegend=True),
                row=current_row, col=1
            )
        else:
            fig.add_trace(
                go.Bar(name='No Data', x=[0], y=["No namespaces"], orientation='h', 
                       marker=dict(color='#95a5a6'), showlegend=False),
                row=current_row, col=1
            )
        
        current_row += 1

        # Collection metadata mismatches (from LAST generation only - the one that matters)
        if all_collection_mismatches:
            # Fetch mismatch details from mismatches collection
            task_ids = [cm["_id"] for cm in all_collection_mismatches[:50]]
            mismatch_details = {}
            try:
                mismatches = list(db.mismatches.find(
                    {"task": {"$in": task_ids}},
                    {"task": 1, "detail": 1}
                ))
                for m in mismatches:
                    mismatch_details[m["task"]] = m.get("detail", {})
            except Exception as e:
                logger.warning(f"Failed to fetch mismatch details: {e}")
            
            coll_headers = ['Generation', 'Namespace', 'Index/Metadata Issues']
            coll_gens = []
            coll_namespaces = []
            coll_details = []
            
            for cm in all_collection_mismatches[:100]:
                coll_gens.append(get_generation_name(cm.get("generation")))
                qf = cm.get("query_filter", {})
                ns = qf.get("namespace", "N/A")
                coll_namespaces.append(ns)
                
                # Try to get details from mismatches collection first
                task_id = cm.get("_id")
                if task_id in mismatch_details:
                    detail = mismatch_details[task_id]
                    idx_name = detail.get("id", "?")
                    field_type = detail.get("field", "")
                    details_str = detail.get("details", "")
                    cluster = detail.get("cluster", "")
                    
                    # Parse the details to show meaningful info
                    if "unique" in details_str.lower():
                        if "unique\": true" in details_str and "unique" not in details_str.split("dst:")[1] if "dst:" in details_str else False:
                            coll_details.append(f"Index '{idx_name}': unique constraint missing on {cluster}")
                        else:
                            coll_details.append(f"Index '{idx_name}' ({field_type}): property mismatch - {cluster}")
                    elif "Missing" in details_str:
                        coll_details.append(f"Index '{idx_name}': MISSING on {cluster}")
                    else:
                        # Show truncated details
                        short_details = details_str[:80] + "..." if len(details_str) > 80 else details_str
                        coll_details.append(f"Index '{idx_name}': {short_details}")
                else:
                    # Fallback to failed_docs
                    failed_docs = cm.get("failed_docs", [])
                    if failed_docs:
                        details = [f"{fd.get('id', 'N/A')}: {fd.get('details', 'N/A')}"[:40] for fd in failed_docs[:2]]
                        coll_details.append("; ".join(details))
                    else:
                        coll_details.append("Mismatch detected (check logs for details)")
            
            fig.add_trace(
                go.Table(
                    header=dict(
                        values=coll_headers,
                        fill_color='#8e44ad',
                        font=dict(color='white', size=14),
                        align='center',
                        height=32
                    ),
                    cells=dict(
                        values=[coll_gens, coll_namespaces, coll_details],
                        fill_color='#f8f4fc',
                        font=dict(size=13),
                        align='left',
                        height=28
                    )
                ),
                row=current_row, col=1
            )
        else:
            fig.add_trace(
                go.Table(
                    header=dict(
                        values=['Collection Metadata Status (Final Generation)'],
                        fill_color='#27ae60',
                        font=dict(color='white', size=15),
                        height=32
                    ),
                    cells=dict(
                        values=[[f'✓ No collection metadata mismatches in {get_generation_name(last_gen_num)}']],
                        fill_color='#d5f5e3',
                        font=dict(size=15, color='#27ae60'),
                        height=38
                    )
                ),
                row=current_row, col=1
            )

        # Calculate dynamic height - account for data size
        num_namespaces = len(namespace_stats) if namespace_stats else 1
        num_gen_rows = max(1, len(generations_to_show))
        # Get max failed tasks across generations for height calculation
        max_failed = max([g["failed"] for g in generations_to_show]) if generations_to_show else 0
        base_height = 600 + (num_gen_rows * 280)  # More base height
        ns_height = max(0, (num_namespaces - 5) * 25)
        failed_height = max(0, (max_failed - 10) * 25)
        total_height = min(2200, base_height + ns_height + failed_height)
        
        # Update layout
        fig.update_layout(
            height=total_height,
            width=1300,
            autosize=True,
            title_text="Migration Verifier Dashboard",
            title_x=0.5,
            title_font=dict(size=24, color="#2c3e50"),
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=-0.03,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#ddd",
                borderwidth=1
            ),
            barmode='stack',
            plot_bgcolor="white",
            paper_bgcolor="white",
            margin=dict(t=70, b=70, l=220, r=30)
        )
        
        # Update axes for namespace bar chart
        ns_row = 1 + num_gens + 1
        fig.update_xaxes(title_text="Tasks", row=ns_row, col=1, title_font=dict(size=11))
        fig.update_yaxes(tickfont=dict(size=11), row=ns_row, col=1)

        return json.dumps(fig, cls=PlotlyJSONEncoder)
    
    except Exception as e:
        logger.error(f"Error gathering verifier metrics: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return json.dumps({"error": f"Error gathering metrics: {str(e)}"})


def plotVerifierMetrics(db_name="migration_verification_metadata"):
    """Render the verifier metrics template."""
    from app_config import REFRESH_TIME
    
    refresh_time = REFRESH_TIME
    refresh_time_ms = str(int(refresh_time) * 1000)
    
    return render_template(
        'verifier_metrics.html',
        refresh_time=refresh_time,
        refresh_time_ms=refresh_time_ms,
        db_name=db_name
    )
