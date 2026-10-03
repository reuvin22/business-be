from pydantic import Field, model_validator

from app.schemas.base import CamelModel, UrlText, require_own_files
from app.schemas.enums import RefundMethod


class ReturnPolicyIn(CamelModel):
    """Returns and refunds (section 16)."""

    return_allowed: bool = False
    return_period_days: int | None = Field(default=None, ge=0)
    refund_method: RefundMethod | None = None
    replacement_available: bool = False
    damaged_goods_policy: str = ""
    defective_goods_policy: str = ""
    policy_description: str = ""  # the full policy, typed in
    policy_file_url: UrlText = ""  # ...and/or as a PDF (uploaded with kind=policy); buyers read it inside the app

    @model_validator(mode="after")
    def uploaded_pdf(self):
        require_own_files(self, [self.policy_file_url], "Policy PDF")
        return self


class SupplierProfileIn(CamelModel):
    """What a supplier can do (section 17). Lets retailers search e.g. "suppliers with private label"."""

    manufacturing: bool = False
    private_label: bool = False
    white_label: bool = False
    custom_orders: bool = False
    bulk_orders: bool = False
    export_goods: bool = False
    import_goods: bool = False
    distribution: bool = False
    contract_manufacturing: bool = False
    sample_available: bool = False
    customization_available: bool = False

    def enabled_capabilities(self) -> list[str]:
        """Names of the capabilities that are switched on, e.g. ["privateLabel", "bulkOrders"]."""
        values = self.model_dump(by_alias=True)
        return [name for name, enabled in values.items() if enabled is True]
