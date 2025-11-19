import os
import json
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Request

from .models import (
    GenerateRequest,
    GenerateResponse,
    PageGenerateRequest,
    WorkItemSurpriseMeRequest,
    CycleSurpriseMeRequest,
    ModuleSurpriseMeRequest,
    EpicSurpriseMeRequest,
)
from .prompts import (
    PAGE_TYPE_PROMPTS,
    WORK_ITEM_GENERATION_PROMPTS,
    WORK_ITEM_SURPRISE_ME_PROMPTS,
    PAGE_CONTENT_GENERATION_PROMPTS,
    CYCLE_GENERATION_PROMPTS,
    CYCLE_SURPRISE_ME_PROMPTS,
    MODULE_GENERATION_PROMPTS,
    MODULE_SURPRISE_ME_PROMPTS,
    EPIC_GENERATION_PROMPTS,
    EPIC_SURPRISE_ME_PROMPTS,
)

try:
    from groq import Groq  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Groq = None  # type: ignore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/generate", tags=["generate"])

# Helper function to call Groq API with timeout
async def call_groq_with_timeout(client, model, temperature, messages, max_tokens=None, timeout=30.0):
    """Call Groq API in executor with timeout protection."""
    loop = asyncio.get_event_loop()
    
    def _call_groq():
        kwargs = {
            "model": model,
            "temperature": temperature,
            "messages": messages,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return client.chat.completions.create(**kwargs)
    
    try:
        completion = await asyncio.wait_for(
            loop.run_in_executor(None, _call_groq),
            timeout=timeout
        )
        return completion
    except asyncio.TimeoutError:
        logger.error(f"Groq API call timed out after {timeout} seconds")
        raise HTTPException(status_code=504, detail=f"Groq API request timed out after {timeout} seconds")
    except Exception as exc:
        logger.error(f"Groq API error: {exc}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Groq API error: {str(exc)}")


@router.post("/work-item", response_model=GenerateResponse)
async def generate_work_item(req: GenerateRequest) -> GenerateResponse:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

    if Groq is None:
        raise HTTPException(status_code=500, detail="groq package not installed on server")

    client = Groq(api_key=api_key)

    system_prompt = WORK_ITEM_GENERATION_PROMPTS['system_prompt']

    user_prompt = WORK_ITEM_GENERATION_PROMPTS['user_prompt_template'].format(
        template_title=req.template.title,
        template_content=req.template.content,
        prompt=req.prompt
    )

    completion = await call_groq_with_timeout(
        client=client,
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=0.4,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    content = completion.choices[0].message.content or ""

    # Best-effort parse: if JSON-like present, extract; else use raw content
    title = req.template.title
    description = req.template.content
    parsed = None
    try:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(content[start : end + 1])
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON from Groq response: {e}. Content preview: {content[:200]}")
        parsed = None

    if isinstance(parsed, dict):
        title = parsed.get("title") or title
        description = parsed.get("description") or description
    else:
        # If we got content but couldn't parse, use it as description
        if content.strip():
            description = content.strip()
            first_line = description.splitlines()[0] if description else req.prompt
            title = first_line[:120] if len(first_line) > 120 else first_line
        else:
            # No content from API, use template defaults
            description = req.template.content
            title = req.template.title

    return GenerateResponse(title=title.strip(), description=description.strip())


@router.post("/work-item-surprise-me", response_model=GenerateResponse)
async def generate_work_item_surprise_me(req: WorkItemSurpriseMeRequest) -> GenerateResponse:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

    if Groq is None:
        raise HTTPException(status_code=500, detail="groq package not installed on server")

    client = Groq(api_key=api_key)

    # Decide behavior based on whether a description was provided
    provided_description = (req.description or "").strip()
    if provided_description:
        system_prompt = WORK_ITEM_SURPRISE_ME_PROMPTS['with_description']['system_prompt']
        user_prompt = WORK_ITEM_SURPRISE_ME_PROMPTS['with_description']['user_prompt_template'].format(
            title=req.title,
            description=provided_description
        )
    else:
        system_prompt = WORK_ITEM_SURPRISE_ME_PROMPTS['without_description']['system_prompt']
        user_prompt = WORK_ITEM_SURPRISE_ME_PROMPTS['without_description']['user_prompt_template'].format(
            title=req.title
        )

    completion = await call_groq_with_timeout(
        client=client,
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=0.4,
        max_tokens=512,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    # The model is instructed to return ONLY markdown description
    generated_description = (completion.choices[0].message.content or "").strip()

    # Always return the original title and the generated markdown description
    return GenerateResponse(title=(req.title or "").strip(), description=generated_description)


@router.options("/stream-page-content")
async def options_page_content():
    return {"message": "OK"}


@router.get("/stream-page-content")
async def generate_page_content(request: Request):
    try:
        data_param = request.query_params.get("data")
        if not data_param:
            raise HTTPException(status_code=400, detail="No data parameter provided")

        data = json.loads(data_param)
        req = PageGenerateRequest(**data)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request data: {e}")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

    if Groq is None:
        raise HTTPException(status_code=500, detail="groq package not installed on server")

    client = Groq(api_key=api_key)

    context = req.context
    page_type = context.page.get('type', 'DOCUMENTATION')

    page_prompt_dict = PAGE_TYPE_PROMPTS.get(page_type, PAGE_TYPE_PROMPTS['DOCUMENTATION'])

    system_prompt = PAGE_CONTENT_GENERATION_PROMPTS['system_prompt_template'].format(
        page_type=page_type,
        page_prompt_dict=page_prompt_dict,
        prompt=req.prompt
    )

    completion = await call_groq_with_timeout(
        client=client,
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=0.4,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Generate professional business content for this {page_type} page in the specified Editor.js block format. Focus on enterprise business context with KPIs, metrics, project management terminology, and structured reporting. Ensure the content is suitable for business stakeholders and executive decision-making. User request: {req.prompt}"}
        ]
    )

    content = completion.choices[0].message.content or "{}"

    try:
        parsed_response = json.loads(content)
        if "blocks" in parsed_response and isinstance(parsed_response["blocks"], list):
            return parsed_response
        else:
            return {
                "blocks": [
                    {
                        "id": "fallback_1",
                        "type": "paragraph",
                        "data": {"text": content.strip() or "Content generation failed"}
                    }
                ]
            }
    except json.JSONDecodeError:
        return {
            "blocks": [
                {
                    "id": "fallback_1",
                    "type": "paragraph",
                    "data": {"text": content.strip() or "Content generation failed"}
                }
            ]
        }


@router.post("/cycle", response_model=GenerateResponse)
async def generate_cycle(req: GenerateRequest) -> GenerateResponse:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

    if Groq is None:
        raise HTTPException(status_code=500, detail="groq package not installed on server")

    client = Groq(api_key=api_key)

    system_prompt = CYCLE_GENERATION_PROMPTS['system_prompt']

    user_prompt = CYCLE_GENERATION_PROMPTS['user_prompt_template'].format(
        template_title=req.template.title,
        template_content=req.template.content,
        prompt=req.prompt
    )

    completion = await call_groq_with_timeout(
        client=client,
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=0.4,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    content = completion.choices[0].message.content or ""

    # Parse JSON response
    title = req.template.title
    description = req.template.content
    parsed = None
    try:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(content[start : end + 1])
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON from Groq response: {e}. Content preview: {content[:200]}")
        parsed = None

    if isinstance(parsed, dict):
        title = parsed.get("title") or title
        description = parsed.get("description") or description
    else:
        if content.strip():
            description = content.strip()
            first_line = description.splitlines()[0] if description else req.prompt
            title = first_line[:120] if len(first_line) > 120 else first_line
        else:
            description = req.template.content
            title = req.template.title

    return GenerateResponse(title=title.strip(), description=description.strip())


@router.post("/cycle-surprise-me", response_model=GenerateResponse)
async def generate_cycle_surprise_me(req: CycleSurpriseMeRequest) -> GenerateResponse:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

    if Groq is None:
        raise HTTPException(status_code=500, detail="groq package not installed on server")

    client = Groq(api_key=api_key)

    # Decide behavior based on whether a description was provided
    provided_description = (req.description or "").strip()
    if provided_description:
        system_prompt = CYCLE_SURPRISE_ME_PROMPTS['with_description']['system_prompt']
        user_prompt = CYCLE_SURPRISE_ME_PROMPTS['with_description']['user_prompt_template'].format(
            title=req.title,
            description=provided_description
        )
    else:
        system_prompt = CYCLE_SURPRISE_ME_PROMPTS['without_description']['system_prompt']
        user_prompt = CYCLE_SURPRISE_ME_PROMPTS['without_description']['user_prompt_template'].format(
            title=req.title
        )

    completion = await call_groq_with_timeout(
        client=client,
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=0.4,
        max_tokens=512,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    generated_description = (completion.choices[0].message.content or "").strip()

    return GenerateResponse(title=(req.title or "").strip(), description=generated_description)


@router.post("/epic", response_model=GenerateResponse)
async def generate_epic(req: GenerateRequest) -> GenerateResponse:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

    if Groq is None:
        raise HTTPException(status_code=500, detail="groq package not installed on server")

    client = Groq(api_key=api_key)

    system_prompt = EPIC_GENERATION_PROMPTS['system_prompt']

    user_prompt = EPIC_GENERATION_PROMPTS['user_prompt_template'].format(
        template_title=req.template.title,
        template_content=req.template.content,
        prompt=req.prompt
    )

    completion = await call_groq_with_timeout(
        client=client,
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=0.4,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    content = completion.choices[0].message.content or ""

    title = req.template.title
    description = req.template.content
    parsed = None
    try:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(content[start: end + 1])
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON from Groq response: {e}. Content preview: {content[:200]}")
        parsed = None

    if isinstance(parsed, dict):
        title = parsed.get("title") or title
        description = parsed.get("description") or description
    else:
        if content.strip():
            description = content.strip()
            first_line = description.splitlines()[0] if description else req.prompt
            title = first_line[:120] if len(first_line) > 120 else first_line
        else:
            description = req.template.content
            title = req.template.title

    return GenerateResponse(title=title.strip(), description=description.strip())


@router.post("/epic-surprise-me", response_model=GenerateResponse)
async def generate_epic_surprise_me(req: EpicSurpriseMeRequest) -> GenerateResponse:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

    if Groq is None:
        raise HTTPException(status_code=500, detail="groq package not installed on server")

    client = Groq(api_key=api_key)

    provided_description = (req.description or "").strip()
    if provided_description:
        system_prompt = EPIC_SURPRISE_ME_PROMPTS['with_description']['system_prompt']
        user_prompt = EPIC_SURPRISE_ME_PROMPTS['with_description']['user_prompt_template'].format(
            title=req.title,
            description=provided_description
        )
    else:
        system_prompt = EPIC_SURPRISE_ME_PROMPTS['without_description']['system_prompt']
        user_prompt = EPIC_SURPRISE_ME_PROMPTS['without_description']['user_prompt_template'].format(
            title=req.title
        )

    completion = await call_groq_with_timeout(
        client=client,
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=0.4,
        max_tokens=512,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    generated_description = (completion.choices[0].message.content or "").strip()

    return GenerateResponse(title=(req.title or "").strip(), description=generated_description)

@router.post("/module", response_model=GenerateResponse)
async def generate_module(req: GenerateRequest) -> GenerateResponse:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

    if Groq is None:
        raise HTTPException(status_code=500, detail="groq package not installed on server")

    client = Groq(api_key=api_key)

    system_prompt = MODULE_GENERATION_PROMPTS['system_prompt']

    user_prompt = MODULE_GENERATION_PROMPTS['user_prompt_template'].format(
        template_title=req.template.title,
        template_content=req.template.content,
        prompt=req.prompt
    )

    completion = await call_groq_with_timeout(
        client=client,
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=0.4,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    content = completion.choices[0].message.content or ""

    # Parse JSON response
    title = req.template.title
    description = req.template.content
    parsed = None
    try:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(content[start : end + 1])
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON from Groq response: {e}. Content preview: {content[:200]}")
        parsed = None

    if isinstance(parsed, dict):
        title = parsed.get("title") or title
        description = parsed.get("description") or description
    else:
        if content.strip():
            description = content.strip()
            first_line = description.splitlines()[0] if description else req.prompt
            title = first_line[:120] if len(first_line) > 120 else first_line
        else:
            description = req.template.content
            title = req.template.title

    return GenerateResponse(title=title.strip(), description=description.strip())


@router.post("/module-surprise-me", response_model=GenerateResponse)
async def generate_module_surprise_me(req: ModuleSurpriseMeRequest) -> GenerateResponse:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

    if Groq is None:
        raise HTTPException(status_code=500, detail="groq package not installed on server")

    client = Groq(api_key=api_key)

    # Decide behavior based on whether a description was provided
    provided_description = (req.description or "").strip()
    if provided_description:
        system_prompt = MODULE_SURPRISE_ME_PROMPTS['with_description']['system_prompt']
        user_prompt = MODULE_SURPRISE_ME_PROMPTS['with_description']['user_prompt_template'].format(
            title=req.title,
            description=provided_description
        )
    else:
        system_prompt = MODULE_SURPRISE_ME_PROMPTS['without_description']['system_prompt']
        user_prompt = MODULE_SURPRISE_ME_PROMPTS['without_description']['user_prompt_template'].format(
            title=req.title
        )

    completion = await call_groq_with_timeout(
        client=client,
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=0.4,
        max_tokens=512,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    generated_description = (completion.choices[0].message.content or "").strip()

    return GenerateResponse(title=(req.title or "").strip(), description=generated_description)

