from app import create_app
from app.celery_app import celery

app = create_app()
app.app_context().push()

# Import tasks so celery discovers them
import app.tasks  # noqa: F401
