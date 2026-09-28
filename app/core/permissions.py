from app.schemas.enums import MemberRole, Permission

ALL_PERMISSIONS = list(Permission)

# The permissions a new member gets for their role. They can be changed per member afterwards.
ROLE_PERMISSIONS: dict[MemberRole, list[Permission]] = {
    MemberRole.OWNER: ALL_PERMISSIONS,
    MemberRole.ADMIN: ALL_PERMISSIONS,
    MemberRole.MANAGER: [p for p in ALL_PERMISSIONS if p != Permission.MANAGE_MEMBERS],
    MemberRole.SALES: [
        Permission.MANAGE_PRODUCTS,
        Permission.MANAGE_SALES_ORDERS,
        Permission.SEND_MESSAGES,
        Permission.MANAGE_RELATIONSHIPS,
    ],
    MemberRole.PURCHASING: [
        Permission.PLACE_ORDERS,
        Permission.SEND_MESSAGES,
        Permission.MANAGE_RELATIONSHIPS,
        Permission.WRITE_REVIEWS,
    ],
    MemberRole.ACCOUNTING: [Permission.MANAGE_PAYMENTS],
    MemberRole.WAREHOUSE: [Permission.MANAGE_INVENTORY, Permission.MANAGE_SALES_ORDERS, Permission.USE_POS],
    MemberRole.STAFF: [],  # can view everything, change nothing
    # Sellers only use the selling app, at the location they were given
    MemberRole.SELLER: [Permission.USE_POS],
}
