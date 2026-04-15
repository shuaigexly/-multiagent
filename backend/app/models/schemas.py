from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, model_validator


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


class TaskResultsResponse(BaseModel):
    task_id: str
    task_type_label: str
    status: str
    result_summary: Optional[str]
    agent_results: List[AgentResultOut]
    published_assets: List[dict]


class PublishRequest(BaseModel):
    asset_types: List[str]   # ["doc", "bitable", "message", "task"]
    doc_title: Optional[str] = None
    chat_id: Optional[str] = None


class PublishResponse(BaseModel):
    published: List[dict]


class TaskListItem(BaseModel):
    id: str
    status: str
    task_type_label: Optional[str]
    input_text: Optional[str]
    created_at: datetime
