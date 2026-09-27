"""File uploads."""

from fastapi import APIRouter, Depends, UploadFile, status

from app.controllers import upload_controller
from app.dependencies.business_access import BusinessAccess, get_business_access
from app.schemas.upload import UploadedImage

router = APIRouter(prefix="/businesses/{business_id}", tags=["Uploads"])


@router.post("/images", response_model=UploadedImage, status_code=status.HTTP_201_CREATED)
def upload_image(file: UploadFile, access: BusinessAccess = Depends(get_business_access)):
    """Upload one image (JPG, PNG, WEBP, or GIF, up to 5 MB). Send it as form data in a field named "file".
    Returns the public URL to save on a product (or anywhere else).

    A normal (not async) function on purpose: the upload waits on the network, and FastAPI runs
    normal functions in a worker thread so other requests are not blocked meanwhile."""
    url = upload_controller.upload_business_image(access, file)
    return UploadedImage(url=url)
