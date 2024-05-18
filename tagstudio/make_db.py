from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from src.database.manage import drop_tables, make_engine, make_tables
from src.database.table_declarations.entry import Entry
from src.database.table_declarations.field import TagBoxField, TextField, TextFieldTypes
from src.database.table_declarations.tag import Tag, TagAlias

if __name__ == "__main__":
    path = Path(__file__).parent

    engine = make_engine(f"sqlite:///{path / "tagstudio.sqlite"}")

    drop_tables(engine=engine)
    make_tables(engine=engine)

    session = Session(engine)

    archived_tag = Tag(
        name="Archived",
        aliases=[TagAlias(name="archives")],
        subtags=set(),
        color="Blue",
        shorthand="arc",
        icon="foo",
    )

    child_tag = Tag(
        name="Child",
        aliases=[],
        subtags=set(),
        color="Red",
        shorthand="chi",
        icon="foo",
    )

    parent_tag = Tag(
        name="Parent",
        aliases=[],
        subtags=set([child_tag]),
        color="Green",
        shorthand="par",
        icon="foo",
    )

    example_entry = Entry(
        filename="foo.png",
        path="/bar",
        fields=[
            TagBoxField(tags=set([parent_tag, archived_tag])),
            TextField(type=TextFieldTypes.text_box, value="An example block of text."),
        ],
    )

    session.add_all([archived_tag, parent_tag, child_tag, example_entry])
    session.commit()
    session.close()

    tags = session.scalars(select(Tag))
    entry = session.scalar(select(Entry))

    if not entry:
        raise ValueError("No Entry.")

    print("Tags:")
    for tag in tags:
        print(f"\tName: {tag.name}")
        print(f"\tSubtags: {[tag.name for tag in tag.subtags]}")
        print(f"\tParents: {[tag.name for tag in tag.parent_tags]}")
        print("\n")

    print("Example Entry:")
    print(f"\tFile name: {entry.filename}")
    print(f"\tNumber of fields: {len(entry.fields)}")
    print(f"\tFirst text field value: {entry.text_fields[0].value}")
    print(f"\tFirst tag box tag's name: {list(entry.tag_box_fields[0].tags)[0].name}")
    print("\tTags:")
    for tag in entry.tags:
        print(f"\t\tName: {tag.name}")
        print(f"\t\tSubtags: {[tag.name for tag in tag.subtags]}")
        print(f"\t\tParents: {[tag.name for tag in tag.parent_tags]}")
        print("\n")
