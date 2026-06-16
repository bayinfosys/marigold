"""API route assembly.

Imports all sub-routers and includes them into a single AWSAPIRouter.
main.py includes this router on the FastAPI app.
"""

from fastapi_aws import AWSAPIRouter

from .embed import router as embed_router
from .eval import router as eval_router
from .gen import router as gen_router
from .output import router as output_router
from .users import router as users_router
from .usage import router as usage_router
from .catalogue import router as catalogue_router

try:
    from ..workflow.routes import router as workflow_router
    _has_workflow = True
except ImportError:
    _has_workflow = False

router = AWSAPIRouter()

router.include_router(embed_router, tags=["embed"])
router.include_router(eval_router, tags=["eval"])
router.include_router(gen_router, tags=["gen"])
router.include_router(output_router, tags=["polling"])
router.include_router(users_router, tags=["users"])
router.include_router(usage_router, tags=["usage"])
router.include_router(catalogue_router, tags=["api"])

if _has_workflow:
    router.include_router(workflow_router, prefix="/workflows", tags=["workflow"])
