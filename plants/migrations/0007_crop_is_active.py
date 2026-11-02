from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("plants", "0006_delete_group")]

    operations = [
        migrations.AddField(
            model_name="crop",
            name="is_active",
            field=models.BooleanField(default=True, verbose_name="선택 가능"),
        ),
    ]
