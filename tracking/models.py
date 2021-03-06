from django.db import models

from vehicle.models import Vehicle
from camera.models import Camera

# Create your models here.


class VehicleLog(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='tracking')
    date = models.DateTimeField()
    lat = models.DecimalField(blank=True, max_digits=9, decimal_places=6, default=None)
    long = models.DecimalField(blank=True ,max_digits=9, decimal_places=6, default=None)
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name='tracking', blank=True, null=True, default=None)
