"""Output formatters for things-cli."""

import json
import sys


def _truncate(value: str | None, width: int) -> str:
    if not value:
        return ""
    v = value.replace("\n", " ").replace("\t", " ")
    if len(v) > width:
        return v[: width - 1] + "…"
    return v


def print_todos(todos: list[dict], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps({"todos": todos}, indent=2))
        return
    if not todos:
        print("No todos.")
        return
    for t in todos:
        project = t.get("project_name") or t.get("area_name") or "-"
        due = t.get("due_date") or "-"
        tags = ", ".join(t.get("tag_names") or []) or "-"
        print(
            f"{t['id']}  [{t['status']:<9}]  {_truncate(t['name'], 40):<40}  "
            f"project/area: {_truncate(project, 20):<20}  due: {due:<10}  tags: {tags}"
        )


def print_todo(todo: dict, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps({"todo": todo}, indent=2))
        return
    print(f"id:                 {todo['id']}")
    print(f"name:               {todo['name']}")
    print(f"status:             {todo['status']}")
    print(
        f"project:            {todo.get('project_name') or '-'} ({todo.get('project_id') or '-'})"
    )
    print(f"area:               {todo.get('area_name') or '-'} ({todo.get('area_id') or '-'})")
    print(f"tags:               {', '.join(todo.get('tag_names') or []) or '-'}")
    print(f"due date:           {todo.get('due_date') or '-'}")
    print(f"activation date:    {todo.get('activation_date') or '-'}")
    print(f"completion date:    {todo.get('completion_date') or '-'}")
    print(f"cancellation date:  {todo.get('cancellation_date') or '-'}")
    print(f"creation date:      {todo.get('creation_date') or '-'}")
    print(f"modification date:  {todo.get('modification_date') or '-'}")
    notes = todo.get("notes") or ""
    if notes:
        print("notes:")
        for line in notes.splitlines():
            print(f"  {line}")


def print_projects(projects: list[dict], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps({"projects": projects}, indent=2))
        return
    if not projects:
        print("No projects.")
        return
    for p in projects:
        area = p.get("area_name") or "-"
        due = p.get("due_date") or "-"
        tags = ", ".join(p.get("tag_names") or []) or "-"
        print(
            f"{p['id']}  [{p['status']:<9}]  {_truncate(p['name'], 40):<40}  "
            f"area: {_truncate(area, 20):<20}  due: {due:<10}  tags: {tags}"
        )


def print_project(project: dict, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps({"project": project}, indent=2))
        return
    print(f"id:                 {project['id']}")
    print(f"name:               {project['name']}")
    print(f"status:             {project['status']}")
    print(
        f"area:               {project.get('area_name') or '-'} ({project.get('area_id') or '-'})"
    )
    print(f"tags:               {', '.join(project.get('tag_names') or []) or '-'}")
    print(f"due date:           {project.get('due_date') or '-'}")
    print(f"activation date:    {project.get('activation_date') or '-'}")
    print(f"completion date:    {project.get('completion_date') or '-'}")
    print(f"cancellation date:  {project.get('cancellation_date') or '-'}")
    print(f"creation date:      {project.get('creation_date') or '-'}")
    print(f"modification date:  {project.get('modification_date') or '-'}")
    notes = project.get("notes") or ""
    if notes:
        print("notes:")
        for line in notes.splitlines():
            print(f"  {line}")


def print_areas(areas: list[dict], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps({"areas": areas}, indent=2))
        return
    if not areas:
        print("No areas.")
        return
    for a in areas:
        tags = ", ".join(a.get("tag_names") or []) or "-"
        print(f"{a['id']}  {_truncate(a['name'], 40):<40}  tags: {tags}")


def print_area(area: dict, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps({"area": area}, indent=2))
        return
    print(f"id:    {area['id']}")
    print(f"name:  {area['name']}")
    print(f"tags:  {', '.join(area.get('tag_names') or []) or '-'}")


def error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
