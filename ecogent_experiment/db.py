import json
import os
import uuid
from datetime import datetime

class ProjectDB:
    """
    Dedicated local JSON DB to manage projects, tracking token costs, chat histories,
    and isolating workflows and tools.
    """
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.data_dir = os.path.join(root_dir, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "db.json")
        self.projects_dir = os.path.join(root_dir, "projects")
        os.makedirs(self.projects_dir, exist_ok=True)
        self._ensure_db()

    def _ensure_db(self):
        if not os.path.exists(self.db_path):
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump({"projects": {}}, f, indent=4)

    def _load(self) -> dict:
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"projects": {}}

    def _save(self, data: dict):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def list_projects(self) -> dict:
        return self._load().get("projects", {})

    def get_project(self, project_id: str) -> dict:
        return self._load().get("projects", {}).get(project_id)

    def create_project(self, name: str) -> str:
        project_id = f"proj_{uuid.uuid4().hex[:8]}"
        proj_dir = os.path.join(self.projects_dir, project_id)
        os.makedirs(proj_dir, exist_ok=True)
        
        # Isolate tools directory
        tools_dir = os.path.join(proj_dir, "tools")
        os.makedirs(tools_dir, exist_ok=True)
        with open(os.path.join(tools_dir, "__init__.py"), "w") as f:
            f.write("")
            
        # Create output workspace directory instantly
        workspace_dir = os.path.join(self.root_dir, "output", name)
        os.makedirs(workspace_dir, exist_ok=True)
            
        # Isolate chat history file and allocate workspace_dir inside
        chat_file = os.path.join(proj_dir, "chat.json")
        with open(chat_file, "w", encoding="utf-8") as f:
            json.dump({
                "id": project_id, 
                "workspace_dir": os.path.relpath(workspace_dir, self.root_dir),
                "history": []
            }, f, indent=4)
            
        data = self._load()
        if "projects" not in data:
            data["projects"] = {}
            
        data["projects"][project_id] = {
            "name": name,
            "created_at": datetime.now().isoformat(),
            "input_tokens": 0,
            "output_tokens": 0,
            "dir": os.path.relpath(proj_dir, self.root_dir),
            "chat_history_file": os.path.relpath(chat_file, self.root_dir),
            "workflow_file": os.path.relpath(os.path.join(proj_dir, "plan.json"), self.root_dir),
            "tools_dir": os.path.relpath(tools_dir, self.root_dir)
        }
        self._save(data)
        return project_id

    def update_metrics(self, project_id: str, input_tokens: int, output_tokens: int):
        """Update token usage metrics for a project."""
        data = self._load()
        project = data.get("projects", {}).get(project_id)
        if project:
            project["input_tokens"] += input_tokens
            project["output_tokens"] += output_tokens
            self._save(data)

    def append_chat(self, project_id: str, message: dict):
        proj = self.get_project(project_id)
        if not proj:
            return
            
        chat_file = os.path.join(self.root_dir, proj["chat_history_file"])
        try:
            with open(chat_file, "r", encoding="utf-8") as f:
                chat_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            chat_data = {"id": project_id, "history": []}
            
        chat_data["history"].append(message)
        
        with open(chat_file, "w", encoding="utf-8") as f:
            json.dump(chat_data, f, indent=4)

    def delete_project(self, project_id: str) -> bool:
        """Deletes a project and its associated files."""
        data = self._load()
        if "projects" in data and project_id in data["projects"]:
            proj = data["projects"][project_id]
            import shutil
            # Remove project directory
            proj_dir = os.path.join(self.root_dir, proj.get("dir", ""))
            if os.path.exists(proj_dir) and os.path.isdir(proj_dir):
                shutil.rmtree(proj_dir, ignore_errors=True)
            
            # Remove project from DB
            del data["projects"][project_id]
            self._save(data)
            return True
        return False
