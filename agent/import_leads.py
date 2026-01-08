from langchain_core.tools import tool
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

@tool
async def import_leads_tool(reason: str = "") -> str:
    """
    Re-open import UI using previously generated leads.
    
    This tool triggers the import UI in the frontend to import leads
    that were previously generated using the lead_enrichment tool.
    
    DOES NOT generate new leads - only opens import UI for existing leads.
    
    Args:
        reason: Optional reason/context for the import action
        
    Returns:
        Special signal to stop agent execution and trigger import UI
    """
    logger.info("[import_leads_tool] ========== IMPORT TOOL STARTED ==========")
    logger.info(f"[import_leads_tool] Reason: {reason}")
    
    try:
        # Step 1: Get websocket connection
        from agent.tools import get_generation_websocket
        ws = get_generation_websocket()
        
        if not ws:
            logger.error("[import_leads_tool] No active websocket connection")
            return "❌ No active websocket connection. Please try again."
        
        logger.info("[import_leads_tool] ✓ Websocket connection found")
        
        # Step 2: Get user_id from global context
        user_id = None
        try:
            import websocket_handler
            user_id = websocket_handler.user_id_global
            logger.info(f"[import_leads_tool] ✓ User ID: {user_id}")
        except Exception as e:
            logger.error(f"[import_leads_tool] Could not get user_id: {e}", exc_info=True)
            return "❌ Could not identify user session"
        
        if not user_id:
            logger.error("[import_leads_tool] user_id is None")
            return "❌ No active user session"
        
        # Step 3: Get recent leads from ws_manager
        try:
            from websocket_handler import ws_manager
            recent_leads = ws_manager.get_recent_leads(user_id)
            logger.info(f"[import_leads_tool] Recent leads retrieved: {recent_leads is not None}")
            
            if recent_leads:
                logger.info(f"[import_leads_tool] Lead count: {recent_leads.get('count', 0)}")
                logger.info(f"[import_leads_tool] Business type: {recent_leads.get('business_type', 'N/A')}")
                logger.info(f"[import_leads_tool] Location: {recent_leads.get('location', 'N/A')}")
        except Exception as e:
            logger.error(f"[import_leads_tool] Could not access ws_manager: {e}", exc_info=True)
            return "❌ System error accessing lead data"
        
        if not recent_leads:
            logger.warning("[import_leads_tool] No recent leads found in cache")
            return "❌ No leads available to import. Please generate leads first using: 'Find [business type] in [city]'"
        
        # Step 4: Send import signal to frontend
        try:
            import_payload = {
                "type": "leads_ready_for_import",
                "leads": recent_leads.get("leads", []),
                "count": recent_leads.get("count", 0),
                "business_type": recent_leads.get("business_type", ""),
                "location": recent_leads.get("location", ""),
                "download_url": recent_leads.get("download_url", ""),
                "reason": reason,
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"[import_leads_tool] Sending import signal: {import_payload['count']} leads")
            await ws.send_json(import_payload)
            logger.info("[import_leads_tool] ✓ Import signal sent successfully")
            
        except Exception as e:
            logger.error(f"[import_leads_tool] Failed to send import signal: {e}", exc_info=True)
            return f"❌ Failed to open import UI: {str(e)}"
        
        # Step 5: Return special signal to stop agent execution
        logger.info("[import_leads_tool] ========== RETURNING STOP SIGNAL ==========")
        return "__LEADS_READY_FOR_IMPORT__"
        
    except Exception as e:
        logger.error(f"[import_leads_tool] Unexpected error: {e}", exc_info=True)
        return f"❌ Error opening import UI: {str(e)}"