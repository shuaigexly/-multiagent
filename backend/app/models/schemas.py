from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field, model_validator, field_validator


VALID_MODULES = {
    "data_analyst", "finance_advisor", "seo_advisor",
    "content_manager", "product_manager", "operations_manager", "ceo_assistant",
}
VALID_ASSET_TYPES = {"doc", "bitable", "slides", "message", "task", "card"}


class TaskCreate(BaseModel):
    input_text: Optional[str] = None
    input_file: Optional[str] = None   # file_id from upload
    feishu_context: Optional[dict] = None

    @model_validator(mode="after")
    def check_input(self):
        if not self.input_text and not self.input_file:
            raise ValueError("input_text 或 input_file 至少提供一个")
        return self


class TaskPlanResponse(BaseModel):
    task_id: str
    task_type: str
    task_type_label: str
    selected_modules: List[str]
    reasoning: str


class TaskConfirm(BaseModel):
    selected_modules: List[str]
    user_instructions: Optional[str] = None

    @field_validator("selected_modules")
    @classmethod
    def validate_modules(cls, v):
        v = list(dict.fromkeys(v))  # deduplicate, preserve order
        if not v:
            raise ValueError("至少选择一个模块")
        invalid = set(v) - VALID_MODULES
        if invalid:
            raise ValueError(f"未知模块: {invalid}")
        return v


class TaskEventOut(BaseModel):
    task_id: str
    sequence: int
    event_type: str
    agent_id: Optional[str]
    agent_name: Optional[str]
    payload: Optional[dict]
    created_at: datetime


class ResultSection(BaseModel):
    title: str
    content: str


class AgentResultOut(BaseModel):
    agent_id: str
    agent_name: str
    sections: List[ResultSection]
    action_items: List[str]
    chart_data: List[dict[str, Any]] = Field(default_factory=list)


class TaskResultsResponse(BaseModel):
    task_id: str
    task_type_label: str
    status: str
    result_summary: Optional[str]
    agent_results: List[AgentResultOut]
    published_assets: List[dict]


class PublishRequest(BaseModel):
    asset_types: List[str]
    doc_title: Optional[str] = None
    chat_id: Optional[str] = None

    @field_validator("asset_types")
    @classmethod
    def validate_asset_types(cls, v):
        if not v:
            raise ValueError("asset_types 不能为空")
        invalid = set(v) - VALID_ASSET_TYPES
        if invalid:
            raise ValueError(f"未知资产类型: {invalid}")
        return list(dict.fromkeys(v))

    @field_validator("doc_title")
    @classmethod
    def validate_doc_title(cls, v):
        if v is not None and len(v) > 100:
            raise ValueError("doc_title 不超过 100 字符")
        return v


class PublishResponse(BaseModel):
    published: List[dict]
    errors: dict[str, str] = Field(default_factory=dict)


class TaskListItem(BaseModel):
    id: str
    status: str = Field(description="任务状态：planning、pending、running、done、failed、cancelled")
    task_type_label: Optional[str]
    input_text: Optional[str]
    created_at: datetime
