import portal.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('operaciones', '0007_neighbor_attention'),
    ]

    operations = [
        migrations.AddField(
            model_name='attention',
            name='evidence_image',
            field=models.ImageField(blank=True, max_length=255, null=True, upload_to='atenciones/imagenes/%Y/%m/', validators=[portal.validators.validate_image_file], verbose_name='Imagen de evidencia (máx. 2 MB)'),
        ),
        migrations.AddField(
            model_name='attention',
            name='attachment',
            field=models.FileField(blank=True, max_length=255, null=True, upload_to='atenciones/adjuntos/%Y/%m/', validators=[portal.validators.validate_attachment_file], verbose_name='Documento de respaldo (máx. 5 MB)'),
        ),
        migrations.AddField(
            model_name='evidence',
            name='file',
            field=models.FileField(blank=True, max_length=255, null=True, upload_to='evidencias/%Y/%m/', validators=[portal.validators.validate_attachment_file], verbose_name='Archivo de evidencia (máx. 5 MB)'),
        ),
    ]
