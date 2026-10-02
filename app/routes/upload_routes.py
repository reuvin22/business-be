"""File uploads."""

from fastapi import APIRouter, Depends, UploadFile, status

from app.controllers import upload_controller
from app.dependencies.business_access import BusinessAccess, get_business_access
from app.schemas.upload import UploadedFile

router = APIRouter(prefix="/businesses/{business_id}", tags=["Uploads"])


@router.post("/images", response_model=UploadedFile, status_code=status.HTTP_201_CREATED)
def upload_file(file: UploadFile, kind: str = "product", access: BusinessAccess = Depends(get_business_access)):
    """Upload one file, up to 25 MB. Send it as form data in a field named "file".
    kind: "product" (a JPG, PNG, WEBP, or GIF image, or an MP4, WEBM, or MOV video; saved in business_api/product_img/)
    or "business" (logo/cover, images only; saved in business_api/business_img/).
    Returns the public URL and the media type (IMAGE or VIDEO) to save on a product (or anywhere else).

    A normal (not async) function on purpose: the upload waits on the network, and FastAPI runs
    normal functions in a worker thread so other requests are not blocked meanwhile."""
    url, media_type = upload_controller.upload_business_file(access, file, kind)
    return UploadedFile(url=url, media_type=media_type)
