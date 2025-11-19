import json
import re
from typing import List, Dict, Any, Optional, Tuple
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

import os
from dotenv import load_dotenv
load_dotenv()

from .prompts import (
    WORK_ITEM_TEMPLATE_PROMPT,
    PAGE_TEMPLATE_PROMPT,
    CYCLE_TEMPLATE_PROMPT,
    MODULE_TEMPLATE_PROMPT,
    EPIC_TEMPLATE_PROMPT
)
from .scenrios import SCENARIO_LIBRARY


ALLOWED_PRIORITIES = {"high", "medium", "low"}

groq_api_key = os.getenv("GROQ_API_KEY")
if not groq_api_key:
    raise ValueError("FATAL: GROQ_API_KEY environment variable not set.")

def get_prompt_for_type(prompt_type: str) -> str:
    """Get the appropriate prompt based on template type."""
    prompt_mapping = {
        "work_item": WORK_ITEM_TEMPLATE_PROMPT,
        "page": PAGE_TEMPLATE_PROMPT,
        "cycle": CYCLE_TEMPLATE_PROMPT,
        "module": MODULE_TEMPLATE_PROMPT,
        "epic": EPIC_TEMPLATE_PROMPT,
    }

    # Default to work_item if type not found
    return prompt_mapping.get(prompt_type.lower(), WORK_ITEM_TEMPLATE_PROMPT)

class TemplateGenerator:
    def __init__ (self):
        self.llm = ChatGroq(
            model="openai/gpt-oss-120b",
            temperature=0.1,  # Slightly creative for query understanding
            max_tokens=1024,
            top_p=0.8,
        )

    async def generate_template(self, user_input: str, prompt_type: str = "work_item") -> Dict[str, Any]:
        prompt_key = (prompt_type or "work_item").lower()
        system_prompt = get_prompt_for_type(prompt_key)

        scenario, keyword_hits = self._select_scenario(prompt_key, user_input)
        slug_hint = self._suggest_slug(user_input)
        priority_override = self._extract_priority_override(user_input)
        human_payload = self._build_user_context(
            prompt_key,
            user_input,
            scenario,
            keyword_hits,
            slug_hint,
            priority_override,
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_payload),
        ]

        ai_response = await self.llm.ainvoke(messages)
        content = self._clean_model_output(ai_response.content)

        try:
            template = json.loads(content)
            required_keys = {"id", "name", "description", "title", "content", "priority"}
            if not required_keys.issubset(template.keys()):
                return {"error": "Missing required fields in template output."}

            template = self._post_process_template(
                template,
                scenario,
                slug_hint,
                priority_override,
                prompt_key,
            )
            return template
        except json.JSONDecodeError:
            return {"error": "Failed to parse template. Invalid JSON format."}

    def _clean_model_output(self, content: Optional[str]) -> str:
        if not content:
            return ""
        text = content.strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
        if text.startswith("```"):
            stripped = text.strip("`\n")
            if stripped.startswith("json\n"):
                stripped = stripped[5:]
            text = stripped
        return text.strip()
    
    def _select_scenario(self, prompt_key: str, user_input: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        scenarios = SCENARIO_LIBRARY.get(prompt_key, [])
        if not scenarios or not user_input:
            return None, []

        text = user_input.lower()
        best_scenario: Optional[Dict[str, Any]] = None
        best_score = -1
        best_hits: List[str] = []

        for scenario in scenarios:
            hits = [kw for kw in scenario.get("keywords", []) if kw and kw in text]
            score = len(hits)
            scenario_name = scenario["name"].lower()
            scenario_key = scenario["key"].lower()
            if scenario_name in text:
                score += 3
            if scenario_key in text:
                score += 2
            if score > best_score:
                best_score = score
                best_scenario = scenario
                best_hits = hits

        if best_score <= 0:
            return None, []

        return best_scenario, best_hits

    def _build_user_context(
        self,
        prompt_key: str,
        user_input: str,
        scenario: Optional[Dict[str, Any]],
        keyword_hits: List[str],
        slug_hint: Optional[str],
        priority_override: Optional[str],
    ) -> str:
        trimmed_input = (user_input or "").strip()
        if not scenario:
            guidance = (
                "User Prompt:\n"
                f"{trimmed_input}\n\n"
                "Guidelines:\n"
                "- Stay within the facts supplied above.\n"
                "- Insert TODO placeholders when information is missing.\n"
                "- Output only the JSON structure requested by the system instructions."
            )
            return guidance

        section_lines = "\n".join(
            f"- {section['heading']}: {section['todo']}" for section in scenario.get("sections", [])
        )
        keywords_line = ", ".join(keyword_hits) if keyword_hits else "None detected"
        slug_line = slug_hint or "N/A"
        priority_line = priority_override or "None"

        context = (
            f"Scenario focus: {scenario['name']} (key: {scenario['key']}, emoji: {scenario['emoji']})\n"
            f"Default priority: {scenario['default_priority']}\n"
            f"Priority override requested: {priority_line}\n"
            f"Matched keywords: {keywords_line}\n"
            f"Recommended sections:\n{section_lines}\n"
            f"Suggested slug fragment: {slug_line}\n\n"
            f"User prompt:\n{trimmed_input}\n\n"
            "Remember: use only the information above. For any missing detail, respond with a TODO placeholder rather than inventing it."
        )
        return context

    def _suggest_slug(self, user_input: str) -> Optional[str]:
        if not user_input:
            return None
        normalized = re.sub(r"[^a-z0-9]+", "-", user_input.lower())
        normalized = re.sub(r"-+", "-", normalized).strip("-")
        tokens = [token for token in normalized.split("-") if len(token) > 2]
        if not tokens:
            return None
        return "-".join(tokens[:4])

    def _extract_priority_override(self, user_input: str) -> Optional[str]:
        if not user_input:
            return None
        text = user_input.lower()
        if any(term in text for term in ["urgent", "asap", "critical", "high priority", "blocker"]):
            return "High"
        if any(term in text for term in ["low priority", "not urgent", "nice to have", "whenever"]):
            return "Low"
        if any(term in text for term in ["medium priority", "normal priority", "standard priority"]):
            return "Medium"
        return None

    def _post_process_template(
        self,
        template: Dict[str, Any],
        scenario: Optional[Dict[str, Any]],
        slug_hint: Optional[str],
        priority_override: Optional[str],
        prompt_key: str,
    ) -> Dict[str, Any]:
        if template.get("error") or not scenario:
            return template

        template["id"] = self._normalize_id(template.get("id"), scenario["id_prefix"], slug_hint)
        template["title"] = self._normalize_title(template.get("title"), scenario)
        template["description"] = self._normalize_description(template.get("description"), scenario)
        template["priority"] = self._normalize_priority(
            template.get("priority"), scenario, priority_override
        )
        template["content"] = self._ensure_content_sections(template.get("content"), scenario)
        template["template_type"] = prompt_key
        return template

    def _normalize_id(self, existing_id: Optional[str], prefix: str, slug_hint: Optional[str]) -> str:
        candidate = (existing_id or "").strip()
        candidate = re.sub(r"[^a-z0-9-]+", "-", candidate.lower()).strip("-")
        if candidate.startswith(prefix):
            return candidate
        if candidate:
            tail = candidate
            if tail.startswith(prefix):
                tail = tail[len(prefix):].strip("-")
            return f"{prefix}-{tail}".strip("-")
        if slug_hint:
            cleaned_slug = re.sub(r"[^a-z0-9-]+", "-", slug_hint.lower()).strip("-")
            if cleaned_slug:
                return f"{prefix}-{cleaned_slug}".strip("-")
        return prefix

    def _normalize_title(self, title: Optional[str], scenario: Dict[str, Any]) -> str:
        expected_prefix = f"{scenario['emoji']} "
        base_label = scenario.get("title_label", scenario["name"])
        candidate = (title or "").strip()
        if candidate.startswith(expected_prefix):
            return candidate
        return f"{expected_prefix}{base_label}"

    def _normalize_description(self, description: Optional[str], scenario: Dict[str, Any]) -> str:
        prefix = f"Scenario: {scenario['name']}."
        desc = (description or "").strip()
        if desc.startswith(prefix):
            return desc
        if desc:
            return f"{prefix} {desc}".strip()
        return f"{prefix} {scenario['description']}"

    def _normalize_priority(
        self,
        priority: Optional[str],
        scenario: Dict[str, Any],
        priority_override: Optional[str],
    ) -> str:
        if priority_override and priority_override.lower() in ALLOWED_PRIORITIES:
            return priority_override.capitalize()
        if priority and priority.lower() in ALLOWED_PRIORITIES:
            return priority.capitalize()
        return scenario["default_priority"]

    def _ensure_content_sections(self, content: Optional[str], scenario: Dict[str, Any]) -> str:
        existing_text = (content or "").strip()
        scenario_sections = scenario.get("sections", [])
        scenario_heading_lookup = {section["heading"].lower(): section for section in scenario_sections}

        pattern = re.compile(r"^##\s+(?P<heading>.+?)\s*$", flags=re.MULTILINE)
        matches = list(pattern.finditer(existing_text))
        existing_blocks: Dict[str, str] = {}
        extras: List[str] = []

        if matches:
            preamble = existing_text[:matches[0].start()].strip()
            if preamble:
                extras.append(preamble)

            for idx, match in enumerate(matches):
                heading = match.group("heading").strip()
                start = match.start()
                end = matches[idx + 1].start() if idx + 1 < len(matches) else len(existing_text)
                block = existing_text[start:end].strip()
                if heading.lower() in scenario_heading_lookup:
                    existing_blocks[heading.lower()] = block
                else:
                    extras.append(block)
        elif existing_text:
            extras.append(existing_text)

        normalized_blocks: List[str] = []
        for section in scenario_sections:
            heading = section["heading"]
            heading_lower = heading.lower()
            block = existing_blocks.get(heading_lower)
            if block:
                lines = block.splitlines()
                if not lines:
                    block = f"## {heading}\n- TODO: {section['todo']}"
                else:
                    lines[0] = f"## {heading}"
                    if len(lines) == 1 or not any(line.strip().startswith("-") for line in lines[1:]):
                        block = f"## {heading}\n- TODO: {section['todo']}"
                    else:
                        block = "\n".join(line.rstrip() for line in lines).strip()
            else:
                block = f"## {heading}\n- TODO: {section['todo']}"
            normalized_blocks.append(block.strip())

        normalized_content = "\n\n".join(normalized_blocks).strip()
        if extras:
            extras_text = "\n\n".join(segment.strip() for segment in extras if segment.strip())
            if extras_text:
                if normalized_content:
                    normalized_content = f"{normalized_content}\n\n{extras_text}"
                else:
                    normalized_content = extras_text

        if normalized_content and not normalized_content.endswith("\n"):
            normalized_content += "\n"
        return normalized_content
