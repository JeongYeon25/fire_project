"""모임 제거 4/4: 아무도 모임을 가리키지 않게 된 뒤 Group 모델을 지운다."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plants", "0005_owner_finalize"),
        ("accounts", "0003_personal"),
        ("diary", "0002_owner"),
    ]

    operations = [migrations.DeleteModel(name="Group")]
