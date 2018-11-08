from flask import Flask, request
from flask_restful import Api, Resource, reqparse
from modules.Exceptions import MyAppInstalledOnDeviceError
from Authentication import invalidToken
#importing Database
import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import Database as db

class MyApps(Resource):
    
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('x-token-id', location='headers')
        args = parser.parse_args()
        if db.checkToken(args["x-token-id"]):
            data = request.json
            try:
                appname = data["name"]
                sourceAppName = data["sourceAppName"]
                version = data["version"]
                appType = data["appSourceType"]
            except KeyError:
                return {
                        "code": 1001,
                        "description": "Given request is not valid: {0}"
                    }, 400, {"Content-Type": "application/json"}
            if db.myAppExists(sourceAppName):
                return {
                        "code": 1304,
                        "description": "An app with name %s already exists." % sourceAppName
                    }, 409, {"content-type": "application/json"}
            if appType != "LOCAL_APPSTORE":
                {
                    "code": -1,
                    "description": "This simulator is not able to manage not LOCAL_APPSTORE applications"
                }, 400, {"Content-Type": "application/json"}
            myapp = db.createMyApp(appname, sourceAppName, version, appType)
            del myapp["_id"]
            return myapp, 201, {"content-type": "application/json"}
        else:
            return invalidToken()
        
    def delete(self, myappid):
        parser = reqparse.RequestParser()
        parser.add_argument('x-token-id', location='headers')
        args = parser.parse_args()
        if db.checkToken(args["x-token-id"]):
            try:
                app = db.deleteMyApp(myappid)
            except MyAppInstalledOnDeviceError, e:
                return {"Error": str(e)}, 400, {"Content-type": "application/json"} # TODO: this response is not compared with FogDirector
            del app["_id"]
            return 
        else:
            return invalidToken()

    def get(self):
        return "" # TODO Implement
"""
GET ?searchByName SE TROVA
{
    "myappId": "2715",
    "name": "httpd",
    "_links": {
        "sourceApp": {
            "href": "/api/v1/appmgr/apps/7bdb377d-45fd-4a8e-a17c-5baa244b1f45:latest"
        },
        "icon": {
            "href": "/api/v1/appmgr/localapps/7bdb377d-45fd-4a8e-a17c-5baa244b1f45:latest/icon"
        },
        "configurations": {
            "href": "/api/v1/appmgr/myapps/2715/configurations"
        },
        "summaryState": {
            "href": "/api/v1/appmgr/myapps/2715/summaryState"
        },
        "aggregatedStats": {
            "href": "/api/v1/appmgr/myapps/2715/aggregatedStats"
        },
        "tags": {
            "href": "/api/v1/appmgr/myapps/2715/tags"
        },
        "action": {
            "href": "/api/v1/appmgr/myapps/2715/action"
        },
        "notifications": {
            "href": "/api/v1/appmgr/myapps/2715/notifications"
        },
        "self": {
            "href": "/api/v1/appmgr/myapps/2715"
        }
    } ALTRIMENTI SE NON TROVA {}
}
"""
