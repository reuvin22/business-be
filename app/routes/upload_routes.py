"""File uploads."""

from fastapi import APIRouter, Depends, UploadFile, status

from app.controllers import upload_controller
from app.dependencies.business_access import BusinessAccess, get_business_access
from app.schemas.upload import OpenedFile, UploadedFile

router = APIRouter(prefix="/businesses/{business_id}", tags=["Uploads"])


@router.post("/images", response_model=UploadedFile, status_code=status.HTTP_201_CREATED)
def upload_file(file: UploadFile, kind: str = "product", access: BusinessAccess = Depends(get_business_access)):
    """Upload one file, up to 25 MB. Send it as form data in a field named "file".
    kind: "product" (a JPG, PNG, WEBP, or GIF image, or an MP4, WEBM, or MOV video; saved in product_img/),
    "business" (logo/cover, images only; business_img/), "chat" (photos sent in messages; chat_img/),
    "policy" (the return policy PDF; policy_docs/), "document" (permits, IDs, certificates: PRIVATE), or
    "proof" (a buyer's proof of payment: PRIVATE).
    Returns the URL (for a private file: "private:<key>", opened with GET /files/open) and the media type.

    A normal (not async) function on purpose: the upload waits on the network, and FastAPI runs
    normal functions in a worker thread so other requests are not blocked meanwhile."""
    url, media_type = upload_controller.upload_business_file(access, file, kind)
    return UploadedFile(url=url, media_type=media_type)


@router.get("/files/open", response_model=OpenedFile)
def open_private_file(ref: str, access: BusinessAccess = Depends(get_business_access)):
    """A link to one of the business's private files (permits, IDs, proofs of payment) that works for 5 minutes.
    Only the business's team gets it. Never save the link: ask again when the file is opened."""
    return OpenedFile(url=upload_controller.open_private_file(access, ref))

