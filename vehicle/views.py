from datetime import datetime

from django.shortcuts import render

from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from django.http import HttpResponse
from rest_framework import permissions, filters

from .models import Vehicle, ImageSpace, MarkedVehicle, Damage, Accuracy, DamageModel
from .serializers import VehicleSerializer, MarkedVehicleSerializer, AccuracySerializer
from .utils import check_for_mark, open_cam_rtsp, saps_API, damage_detection
from tracking.serializers import TrackingSerializer, TrackingReturnSerializer
from tracking.models import VehicleLog
from tools.viewsets import ActionAPI, validate_params
from camera.models import Camera

# import cv2
import os
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
import requests
import numpy as np
from openalpr import Alpr
import sys

from custom_user import send_email


class VehicleBase(ActionAPI):
    
    permission_classes = [permissions.IsAuthenticated, ] 
    @csrf_exempt
    @validate_params(['vehicle_id'])
    def get_vehicle(self, request, params=None, *args, **kwargs):
        """
        Simply a way of getting all the information on a specified vehicle
        """
        try:
            vehicle = Vehicle.objects.get(pk=params['vehicle_id'])
        except Vehicle.DoesNotExist:
            return {
                "success": False,
                "message": "Vehicle with that license plate does not exist"
            }

        serializer = VehicleSerializer(vehicle)
        return serializer.data
        
    @csrf_exempt
    @validate_params(['license_plate', 'color', 'make', 'model'])
    def add_vehicle_basic(self, request, params=None, *args, **kwargs):
        """
        Used to add vehicles
        """

        # TODO: Implement SAPS flag checking

        vehicle = Vehicle.objects.filter(license_plate=params['license_plate'])
        check_for_mark(params['license_plate'])

        if vehicle.count() > 0:
            vehicle = vehicle[0]

            if params['make'] != vehicle.make or vehicle.model != params['model'] or vehicle.color != params['color']:
                # This license plate is a duplicate in this case
                vehicle.license_plate_duplicate = True
                vehicle.save()
                data = {
                    "license_plate": params["license_plate"],
                    "make": params["make"],
                    "model": params["model"],
                    "color": params["color"],
                    "saps_flagged": False,
                    "license_plate_duplicate": True
                }

                serializer = VehicleSerializer(data=data)
                if serializer.is_valid():
                    vehicle = serializer.save()
                    tracking_data = {
                        "vehicle": serializer.data.get("id"),
                        "date": datetime.now(),
                        "lat": params.get("lat", 00.000000),
                        "long": params.get("long", 00.000000)
                    }
                    tracking_serializer = TrackingSerializer(data=tracking_data)
                    if tracking_serializer.is_valid():
                        tracking_serializer.save()
                    #adding damage
                    if params["damage"]:
                        dmg_obj = Damage(vehicle=vehicle, location=params.get("damage",None))
                        dmg_obj.save()
                    return {
                        "success": True,
                        "duplicate": True,
                        "payload": {
                            "vehicles": serializer.data
                        }
                    }
                return serializer.errors

            # This vehicle is not a duplicate but already exists within the system
            tracking_data = {
                "vehicle": vehicle,
                "date": datetime.now(),
                "lat": params.get("lat", 00.000000),
                "long": params.get("long", 00.000000)
            }

            tracking_serializer = TrackingSerializer(data=tracking_data)
            if (tracking_serializer.is_valid()):
                tracking_serializer.save()
            #adding damage
            if params["damage"]:
                dmg_obj = Damage(vehicle=vehicle, location=params.get("damage",None))
                dmg_obj.save()

            return {
                "success": True,
                "message": "Vehicle tracked"
            }
        
        # This vehicle is not within our system yet, add it
        data = {
            "license_plate": params["license_plate"],
            "make": params["make"],
            "model": params["model"],
            "color": params["color"],
            "saps_flagged": False, #TODO: Add this checking stuff
            "license_plate_duplicate": False
        }

        serializer = VehicleSerializer(data=data)
        if serializer.is_valid():
            vehicle = serializer.save()

            tracking_data = {
                "vehicle": serializer.data.get("id"),
                "date": datetime.now(),
                "lat": params.get("lat", 00.000000),
                "long": params.get("long", 00.000000)
            }
            tracking_serializer = TrackingSerializer(data=tracking_data)
            if tracking_serializer.is_valid():
                tracking_serializer.save()

            #adding damage
            if params["damage"]:
                dmg_obj = Damage(vehicle=vehicle, location=params.get("damage",None))
                dmg_obj.save()

            return serializer.data
        data = {
            "success": False,
            "payload": serializer.errors
        }
        return data

    @csrf_exempt
    @validate_params(["filters", "type"])
    def search_advanced(self, request, params=None, *args, **kwargs):
        """ 
        Used to search for vehicles by various paramaters
        """

        search_type = params.get("type", None)
        filters_param = params.get('filters', None)

        if search_type == "and":
            """AND TYPE SEARCH"""
            queryset = Vehicle.objects.all()

            if filter is None:
                return {
                    "success": False,
                    "message": "Filters argument not provided"
                }

            license_plate = filters_param.get('license_plate', None)
            make = filters_param.get('make', None)
            model = filters_param.get('model', None)
            color = filters_param.get('color', None)
            saps_flagged = filters_param.get('saps_flagged', None)
            license_plate_duplicate = filters_param.get('license_plate_duplicate', None)
            damage = filters_param.get('damage', None)

            if license_plate:
                queryset = queryset.filter(license_plate=license_plate)

            if make:
                queryset = queryset.filter(make=make)

            if model:
                queryset = queryset.filter(model=model)
            
            if color:
                queryset = queryset.filter(color=color)

            if saps_flagged:
                queryset = queryset.filter(saps_flagged=saps_flagged)

            if license_plate_duplicate:
                queryset = queryset.filter(license_plate_duplicate=license_plate_duplicate)

            if damage:
                queryset = queryset.filter(damage__location__icontains=damage)

            if queryset.count() == 0:
                return {
                    "success": False,
                    "message": "No items match this query"
                }

            serializer = VehicleSerializer(queryset, many=True)

            return serializer.data

        elif search_type == "or":
            """OR TYPE SEARCH"""
            queryset = Vehicle.objects.none()

            license_plate = filters_param.get('license_plate', None)
            make = filters_param.get('make', None)
            model = filters_param.get('model', None)
            color = filters_param.get('color', None)
            saps_flagged = filters_param.get('saps_flagged', None)
            license_plate_duplicate = filters_param.get('license_plate_duplicate', None)
            damage = filters_param.get('damage', None)

            if license_plate:
                queryset |= Vehicle.objects.filter(license_plate=license_plate)
            if make:
                queryset |= Vehicle.objects.filter(make=make)
            if model:
                queryset |= Vehicle.objects.filter(model=model)
            if color:
                queryset |= Vehicle.objects.filter(color=color)
            if saps_flagged:
                queryset |= Vehicle.objects.filter(saps_flagged=saps_flagged)
            if license_plate_duplicate:
                queryset |= Vehicle.objects.filter(license_plate_duplicate=license_plate_duplicate)
            if damage:
                queryset |= Vehicle.objects.filter(damage__location__icontains=damage)
            if queryset.count() == 0:
                return {
                    "success": False,
                    "message": "No data matching query"
                }

            serializer = VehicleSerializer(queryset, many=True)

            return serializer.data

        return {
            "success": False,
            "message": "Search type is not supported"
        }
    
    @validate_params(['search'])
    def search(self, request, params=None, *args, **kwargs):
        """
        Used to search the database of Vehicles by keywords
        """

        # TODO: Consider implementing multiple words?

        word_match = params.get("search", None)

        if word_match is None:
            return {
                "success": False,
                "message": "No search words were passed through"
            }

        queryset = Vehicle.objects.filter(
            Q(license_plate__icontains=word_match) |
            Q(make__icontains=word_match) |
            Q(model__icontains=word_match) |
            Q(color__icontains=word_match) |
            Q(damage__location__icontains=word_match)
        )

        if queryset.count() == 0:
            return {
                "success": False,
                "message": "No items matching given keywords"
            }

        serializer = VehicleSerializer(queryset, many=True)
        return serializer.data

    @csrf_exempt
    def file_recognize(self, request, params=None, *args, **kwargs):
        """
        Used to upload a file and run it through OpenALPR and save an instance of a vehicle to that image
        """

        from lpr.lpr import check_image
        import json


        # TODO: (Steve) I have created a model and serializer for you to use that stores accuracies. Please make the migrations and implement it here
        # The related model is called Accuracy and the serializer AccuracySerializer
        # Then I have also created a new model to store the damage detection model thingy of the vehicle. Please make use of it too (ITS VERY SIMILAR TO THE IMAGESPACE MODEL)


        camera = Camera.objects.get(owner=request.user, name="Manual")

        temp = ImageSpace(image=params['file'])
        temp.save()
        path = temp.image.path

        tracking = {
            "vehicle": None,
            "date": datetime.now(),
            "lat": float(params.get("lat", 00.000000)),
            "long": float(params.get("long", 00.000000)),
            "camera": camera.id
        }

        # TODO: Perhaps consider file size compression or file size too large returns

        regions = ['za'] # Change to your country
        with open(path, 'rb') as fp:
            response = requests.post(
            'https://api.platerecognizer.com/v1/plate-reader/',
            data=dict(regions=regions),  # Optional
            files=dict(upload=fp),
            headers={'Authorization': 'token 8e744c1226777aa96d25e06807b69cbfc03f4c72'})
        res = response.json()
        
        if res.get("error", None):
            return {
                "success": False,
                "message": "Invalid file"
            }

        res = res["results"]

        #if vehicle is missing numberplate
        if len(res) == 0:
            data = {
                "license_plate": "",
                "color": "tbi",
                "make": "tbi",
                "model": "tbi",
                "saps_flagged": False,
                "license_plate_duplicate": False
            }

            serializer = VehicleSerializer(data=data)
            if serializer.is_valid():
                vehicle = serializer.save()
                acc = Accuracy(vehicle=vehicle)
                acc.save()

                from .utils import colour_detection, make_model_detection
                bytes_ret = colour_detection(path, vehicle)
                bytes_ret = bytes_ret.split("\n")
                data["color"] = bytes_ret[0]
                bytes_ret = make_model_detection(path, vehicle)
                bytes_ret = bytes_ret.split(":")
                data["model"] = bytes_ret[0]
                data["make"] = bytes_ret[1]
                
                tracking["vehicle"] = vehicle.id
                tracking_serializer = TrackingSerializer(data=tracking)
                if tracking_serializer.is_valid():
                    tracking_serializer.save()
                temp.vehicle = vehicle
                temp.save()
                
                damage_array = damage_detection(vehicle)
                for damage in damage_array:
                    dmg_obj = Damage(vehicle=vehicle, location=damage)
                    dmg_obj.save()
                return serializer.data

        vehicle_data = []
        image_space_items = []
        image_space_items.append(temp)
        first_iteration = True
        # Init the values for each plate recognized
        #first time seeing this vehicle
        for item in res:
            plate = item["plate"]

            check_for_mark(plate)

            if not first_iteration:
                temp = ImageSpace(image=params['file'])
                temp.save()
                image_space_items.append(temp)
                
            first_iteration = False
            data = {
                "license_plate": plate,
                "color": "tbi",
                "make": "tbi",
                "model": "tbi",
                "saps_flagged": False,
                "license_plate_duplicate": False,
            }

            vehicle_data.append(data)


        # Do the saps flag checks
        for data in vehicle_data:
            saps_flag = saps_API(params={"license_plate": data["license_plate"]}, *args, **kwargs)
            data["saps_flagged"] = saps_flag
        
        duplicate_check = Vehicle.objects.filter(license_plate=data["license_plate"])
        if duplicate_check.count() == 0:
            serializer = VehicleSerializer(data=data)
            if serializer.is_valid():
                vehicle = serializer.save()
                acc = Accuracy(vehicle=vehicle)
                acc.save()
            else:
                return {
                        "success": False,
                        "message": "There is something wrong with the detection of the vehicle"
                    }
        else:
            vehicle = Vehicle.objects.filter(license_plate=data["license_plate"]).order_by("-id")[0]
            acc = Accuracy(vehicle=vehicle)
            acc.save()

        # Do the color detection for the vehicles
        from .utils import colour_detection
        if duplicate_check.count() == 1:
            bytes_ret = colour_detection(path, vehicle)
        else:
            bytes_ret = colour_detection(path, vehicle)

        bytes_ret = bytes_ret.split("\n")
        for i, data in enumerate(vehicle_data):
            data["color"] = bytes_ret[i]

        # Do the make and model detection for the vehicle(s)
        from .utils import make_model_detection
        if duplicate_check.count() == 1:
            bytes_ret = make_model_detection(path, vehicle).split("\n")
        else:
            bytes_ret = make_model_detection(path, vehicle).split("\n")

        for i, data in enumerate(vehicle_data):
            splitter = bytes_ret[i].split(":")
            data["model"] = splitter[0]
            data["make"] = splitter[1]
        
        if duplicate_check.count() == 1:
            vehicle.make = data["make"]
            vehicle.model = data["model"]
            vehicle.color = data["color"]

        vehicles = []
        for i, data in enumerate(vehicle_data):
            
            image_space = image_space_items[i]

            if duplicate_check.count() > 1:

                for duplicate_item in duplicate_check:
                    if duplicate_item.make.lower() == data["make"].lower() and\
                        duplicate_item.model.lower() == data["model"].lower() and\
                        duplicate_item.color.lower() == data["color"].lower():
                        vehicles.append(duplicate_item)
                        tracking["vehicle"] = duplicate_item.id
                        tracking_serializer = TrackingSerializer(data=tracking)
                        if tracking_serializer.is_valid():
                            tracking_serializer.save()
                            image_space.vehicle = duplicate_item
                            image_space.save()
                    else:
                        duplicate_item.license_plate_duplicate = True
                        duplicate_item.save()
                        data["license_plate_duplicate"] = True
                        serializer = VehicleSerializer(data=data)
                        if serializer.is_valid():
                            vehicle = serializer.save()
                            acc = Accuracy(vehicle=vehicle)
                            acc.save()
                            tracking["vehicle"] = vehicle.id
                            tracking_serializer = TrackingSerializer(data=tracking)
                            if tracking_serializer.is_valid():
                                tracking_serializer.save()
                            vehicles.append(vehicle)
                            image_space.vehicle = vehicle
                            image_space.save()
                        else:
                            return {
                                "success": False,
                                "message": "There is something wrong with the detection of the vehicle"
                            }
            else:

                if serializer.is_valid():
                    tracking["vehicle"] = vehicle.id
                    tracking_serializer = TrackingSerializer(data=tracking)
                    if tracking_serializer.is_valid():
                        tracking_serializer.save()
                    vehicles.append(vehicle)
                    image_space.vehicle = vehicle
                    image_space.save()
                else:
                    return {
                        "success": False,
                        "message": "There is something wrong with the detection of the vehicle"
                    }
        
        for vehicle in vehicles:
            if vehicle.saps_flagged:
                from email_engine import EmailEngine
                engine = EmailEngine()
                engine.send_saps_flag_notification(request.user.email, vehicle)
                # tracking_qs = VehicleLog.objects.filter(vehicle__id=vehicle.id).latest("id")
                # location = "Lat: {}, Long: {}".format(tracking_qs.lat, tracking_qs.long)
                # send_email.flagged_notification(
                #     request.user.email,
                #     vehicle.license_plate,
                #     "this vehicle was involved in theft or possibly stolen",
                #     params["file"], location, vehicle.make,
                #     vehicle.model, vehicle.color
                # )
        # damage detection        
        for vehicle in vehicles:
            damage_array = damage_detection(vehicle)
            for damage in damage_array:
                dmg_obj = Damage(vehicle=vehicle, location=damage)
                dmg_obj.save()

                

        serializer = VehicleSerializer(vehicles, many=True)
        return serializer.data
    

    def get_saps_flagged(self, request, params=None, *args, **kwargs):
        """
        Used to retrieve the set of vehicles that have been flagged by SAPS and saved in our system
        """

        queryset = Vehicle.objects.filter(saps_flagged=True)

        serializer = VehicleSerializer(queryset, many=True)

        return serializer.data


    def get_duplicates(self, request, params=None, *args, **kwags):
        """
        Used to retrieve the set of vehicles that are duplicates
        """

        queryset = Vehicle.objects.filter(license_plate_duplicate=True)

        serializer = VehicleSerializer(queryset, many=True)

        return serializer.data


    @validate_params(['license_plate', 'reason'])
    def add_marked_vehicle(self, request, params=None, *args, **kwargs):
        """
        Used to add a marked vehicle
        """

        data = {
            "license_plate": params['license_plate'],
            "marked_by": request.user.id,
            "reason": params["reason"],
        }


        serializer = MarkedVehicleSerializer(data=data)

        if serializer.is_valid():
            serializer.save()
            return {
                "success": True
            }

        return {
            "success": False,
            "payload": serializer.errors
        }

    def get_marked_vehicles(self, request, params=None, *args, **kwargs):
        """
        Used to retrieve a dataset of the marked vehicles by the current auth'd user
        """

        queryset = MarkedVehicle.objects.filter(marked_by=request.user)

        if queryset.count() > 0:
            serializer = MarkedVehicleSerializer(queryset, many=True)
            return serializer.data
        
        return {
            "message": "There are no vehicles marked by this user"
        }

    @validate_params(['license_plate'])
    def remove_marked_vehicle(self, request, params=None, *args, **kwargs):
        """
        Used to remove a marked vehicle
        """

        queryset = MarkedVehicle.objects.filter(license_plate=params['license_plate'])

        if queryset.count() > 0:
            queryset.delete()
            return {
                "success": True
            }

        return {
            "success": False,
            "message": "There are no vehicles marked with that license plate"
        }


    @csrf_exempt
    @validate_params(['vehicle_id'])
    def edit_vehicle(self, request, params=None, *args, **kwargs):
        """
        Used to edit and existing vehicles attributes
        """

        try:
            vehicle = Vehicle.objects.get(pk=params['vehicle_id'])
        except Vehicle.DoesNotExist:
            return {
                "success": False,
                "message": "Vehicle with that license plate does not exist"
            }  

        if (params.get("license_plate_duplicate", None) in [False, 'false', 'False']) and (vehicle.license_plate_duplicate is True) and (params.get("license_plate", None)):
            qs = Vehicle.objects.filter(license_plate=vehicle.license_plate).exclude(id=vehicle.id)
            if qs.count() < 2:
                qs = qs[0]
                qs.license_plate_duplicate = False
                qs.save()
        
        if (params.get("license_plate_duplicate", None) in [True, 'true', 'True']) and (vehicle.license_plate_duplicate is False) and (params.get("license_plate", None)):
            qs = Vehicle.objects.filter(license_plate = params.get("license_plate"))
            for item in qs:
                item.license_plate_duplicate = True
                item.save()

        vehicle.license_plate = params.get("license_plate", vehicle.license_plate)
        vehicle.make = params.get('make', vehicle.make)
        vehicle.model = params.get('model', vehicle.model)
        vehicle.color = params.get('color', vehicle.color)
        vehicle.saps_flagged = params.get('saps_flagged', vehicle.saps_flagged)
        flag = params.get('license_plate_duplicate', vehicle.license_plate_duplicate)
        if flag in [False, 'false', 'False']:
            flag = False
        if flag in [True, 'true', 'True']:
            flag = True
        vehicle.license_plate_duplicate = flag

        vehicle.save()
        serializer = VehicleSerializer(vehicle)

        return serializer.data

    @validate_params(["license_plate"])
    def get_vehicle_locations(self, request, params=None, *args, **kwargs):
        
        vehicles = Vehicle.objects.filter(license_plate__iexact=params["license_plate"])

        if vehicles.count() == 0:
            return {
                "success": False,
                "message": "There are no vehicles with that license plate in the system"
            }

        payload = []
        for vehicle in vehicles:
            tracking_data = vehicle.tracking.all()
            tracking_serializer = TrackingReturnSerializer(tracking_data, many=True)
            temp_data = {
                "vehicle_id": vehicle.id,
                "license_plate": vehicle.license_plate,
                "tracking": tracking_serializer.data
            }
            payload.append(temp_data)

        return {
            "payload": payload
        }

    @validate_params(["license_plate"])
    def get_vehicle_damage(self, request, params=None, *args, **kwargs):
        from .serializers import DamagedVehicleSerializer
        vehicles = Vehicle.objects.filter(license_plate__iexact=params["license_plate"])

        if vehicles.count() == 0:
            return {
                "success": False,
                "message": "There are no vehicles with that license plate in the system"
            }
        
        payload = []
        for vehicle in vehicles:
            damage = vehicle.damage.all()
        damage_serializer = DamagedVehicleSerializer(damage, many=True)
        return {
            "payload": damage_serializer.data
        }

    @validate_params(["vehicle_id"])
    def get_latest_vehicle_image(self, request, params=None, *args, **kwargs):
        """
        Get the latest vehicle image from vehicle id
        """

        image = ImageSpace.objects.filter(vehicle__id=params["vehicle_id"]).last()

        if not image:
            return {
                "success": False,
                "message": "There is no image for that vehicle ID"
            }

        path = image.image.path

        try:
            with open(path, 'rb') as f:
                return HttpResponse(f.read(), content_type="image/jpeg")
        except IOError:
            return {
                "success": False,
                "message": "Error opening vehicle image"
            }

    @validate_params(["vehicle_id"])
    def get_vehicles_damage_detection(self, request, params=None, *args, **kwargs):
        """
        Get the vehicles detected damages
        """

        image = DamageModel.objects.filter(vehicle__id=params["vehicle_id"]).last()

        if not image:
            return{
                "success": False,
                "message": "There seems to be no detection image for that vehicle"
            }

        path = image.image.path

        try:
            with open(path, 'rb') as f:
                return HttpResponse(f.read(), content_type="image/jpeg")
        except IOError:
            return {
                "success": False,
                "message": "Error opening image"
            }

    @validate_params(["vehicle_id"])
    def get_vehicle_accuracy(self, request, params=None, *args, **kwargs):


        acc = Accuracy.objects.get(vehicle__id=params["vehicle_id"])

        if not acc:
            return {
                "success": False,
                "message": "No accuracies found for that vehicle id"
            }

        serializer = AccuracySerializer(acc)

        return serializer.data

    def get_latest_damage_detection_image(self, request, params=None, *args, **kwargs):
        path = "predictions.jpg"
        try:
            with open(path, 'rb') as f:
                return HttpResponse(f.read(), content_type="image/jpeg")
        except IOError:
            return {
                "success": False,
                "message": "Error opening vehicle image"
            }
        
    def get_latest_colour_detection_image(self, request, params=None, *args, **kwargs):
        path = "colour.jpg"
        try:
            with open(path, 'rb') as f:
                return HttpResponse(f.read(), content_type="image/jpeg")
        except IOError:
            return {
                "success": False,
                "message": "Error opening vehicle image"
            }

    def get_latest_make_model_detection_image(self, request, params=None, *args, **kwargs):
        path = "makemodel.jpg"
        try:
            with open(path, 'rb') as f:
                return HttpResponse(f.read(), content_type="image/jpeg")
        except IOError:
            return {
                "success": False,
                "message": "Error opening vehicle image"
            }


    def file_recognize_two(self, request, params=None, *args, **kwargs):

        from .engines import VehicleClassificationEngine

        camera = Camera.objects.get(owner=request.user, name="Manual")
        vehicle = Vehicle()
        temp = ImageSpace(image=params['file'])
        temp.save()
        path = temp.image.path

        tracking = {
            "vehicle": None,
            "date": datetime.now(),
            "lat": float(params.get("lat", 00.000000)),
            "long": float(params.get("long", 00.000000)),
            "camera": camera.id
        }


        engine = VehicleClassificationEngine(vehicle, temp, tracking, to_address=request.user.email)
        result = engine.classify_vehicle()

        if type(result) is str:
            return result
        
        serializer = VehicleSerializer(result)


        # TODO: Saps email quick stix
        return serializer.data

    def test_email(self, request, params=None, *args, **kwargs):
        from email_engine import EmailEngine

        test_vehicle = Vehicle.objects.all().latest("id")
        test_address = "stephendups@gmail.com"

        engine = EmailEngine()
        engine.send_saps_flag_notification(test_address, test_vehicle)

        return "sent"