from dataclasses import dataclass

from src.database.table_declarations.field import (
    DatetimeField,
    DateTimeTypes,
    Field,
    FieldType,
    TagBoxField,
    TagBoxTypes,
    TextField,
    TextFieldTypes,
)


@dataclass
class DefaultField:
    name: str
    class_: Field
    type_: FieldType


TODO = [
    {"id": 9, "name": "Collation", "type": "collation"},
    {"id": 17, "name": "Book", "type": "collation"},
    {"id": 18, "name": "Comic", "type": "collation"},
    {"id": 19, "name": "Series", "type": "collation"},
    {"id": 20, "name": "Manga", "type": "collation"},
    {"id": 24, "name": "Volume", "type": "collation"},
    {"id": 25, "name": "Anthology", "type": "collation"},
    {"id": 26, "name": "Magazine", "type": "collation"},
    {"id": 15, "name": "Archived", "type": "checkbox"},
    {"id": 16, "name": "Favorite", "type": "checkbox"},
]


DEFAULT_FIELDS: list[DefaultField] = [
    DefaultField(name="Title", class_=TextField, type_=TextFieldTypes.text_line),
    DefaultField(name="Author", class_=TextField, type_=TextFieldTypes.text_line),
    DefaultField(name="Artist", class_=TextField, type_=TextFieldTypes.text_line),
    DefaultField(name="Guest Artist", class_=TextField, type_=TextFieldTypes.text_line),
    DefaultField(name="Composer", class_=TextField, type_=TextFieldTypes.text_line),
    DefaultField(name="URL", class_=TextField, type_=TextFieldTypes.text_line),
    DefaultField(name="Source", class_=TextField, type_=TextFieldTypes.text_line),
    DefaultField(name="Publisher", class_=TextField, type_=TextFieldTypes.text_line),
    DefaultField(name="Description", class_=TextField, type_=TextFieldTypes.text_box),
    DefaultField(name="Notes", class_=TextField, type_=TextFieldTypes.text_box),
    DefaultField(name="Comments", class_=TextField, type_=TextFieldTypes.text_box),
    DefaultField(name="Tags", class_=TagBoxField, type_=TagBoxTypes.tag_box),
    DefaultField(name="Content Tags", class_=TagBoxField, type_=TagBoxTypes.tag_box),
    DefaultField(name="Meta Tags", class_=TagBoxField, type_=TagBoxTypes.tag_box),
    DefaultField(name="Date", class_=DatetimeField, type_=DateTimeTypes.datetime),
    DefaultField(
        name="Date Created", class_=DatetimeField, type_=DateTimeTypes.datetime
    ),
    DefaultField(
        name="Date Modified", class_=DatetimeField, type_=DateTimeTypes.datetime
    ),
    DefaultField(name="Date Taken", class_=DatetimeField, type_=DateTimeTypes.datetime),
    DefaultField(
        name="Date Published", class_=DatetimeField, type_=DateTimeTypes.datetime
    ),
    DefaultField(
        name="Date Uploaded", class_=DatetimeField, type_=DateTimeTypes.datetime
    ),
    DefaultField(
        name="Date Released", class_=DatetimeField, type_=DateTimeTypes.datetime
    ),
]
