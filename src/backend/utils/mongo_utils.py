"""MongoDB identifier parsing helpers."""

from bson import ObjectId


def object_id_string(value: ObjectId | str | None) -> str:
    if value is None:
        return str(ObjectId())
    if isinstance(value, ObjectId):
        return str(value)
    if ObjectId.is_valid(value):
        return str(ObjectId(value))
    raise ValueError("Invalid MongoDB ObjectId")
