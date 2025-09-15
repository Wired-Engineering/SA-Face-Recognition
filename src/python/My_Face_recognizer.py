
import cv2
import os
import time
class FaceRecognizer:
    def __init__(self,thresold=0.5,draw=True):
        self.thresold=thresold
        self.draw=draw
        self.unknownmatch=0
        weights ="model/face_detection_yunet_2023mar.onnx"
        self.face_detector = cv2.FaceDetectorYN_create(weights, "", (0, 0))
        self.face_detector.setScoreThreshold(0.87)
        weights = "model/face_recognizer_fast.onnx"
        self.face_recognizer = cv2.FaceRecognizerSF_create(weights, "")
        self.create_features()
    def create_features(self):
        self.dictionary = {}
        files=os.listdir("images")
        files = list(set(files))
        for file in files:
            image = cv2.imread("images/"+file)
            feats, faces = self.recognize_face(image, file)
            if faces is None:
                continue
            user_id = os.path.splitext(os.path.basename(file))[0]
            self.dictionary[user_id] = feats[0]
    def recognize_face(self,image,file_name=None):
        channels = 1 if len(image.shape) == 2 else image.shape[2]
        if channels == 1:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if channels == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

        if image.shape[0] > 1000:
            image = cv2.resize(image, (0, 0),
                            fx=500 / image.shape[0], fy=500 / image.shape[0])
        
        height, width, _ = image.shape
        self.face_detector.setInputSize((width, height))
        try:
            dts = time.time()
            _, faces = self.face_detector.detect(image)
            if file_name is not None:
                assert len(faces) > 0, f'the file {file_name} has no face'

            faces = faces if faces is not None else []
            features = []
            #print(f'time detection  = {time.time() - dts}')
            for face in faces:
                rts = time.time()
                aligned_face = self.face_recognizer.alignCrop(image, face)
                feat = self.face_recognizer.feature(aligned_face)
                #print(f'time recognition  = {time.time() - rts}')
                features.append(feat)
            return features, faces
        except Exception as e:
            print(e)
            print(file_name)
            return None, None
    def match(self, feature1):
        max_score = 0.0
        sim_user_id = ""
        for user_id, feature2 in zip(self.dictionary.keys(), self.dictionary.values()):
            score = self.face_recognizer.match(feature1, feature2, cv2.FaceRecognizerSF_FR_COSINE)
            if score >= max_score:
                max_score = score
                sim_user_id = user_id
        if max_score < self.thresold:
            return False, ("", 0.0)
        return True, (sim_user_id, max_score)
    def detect(self,image):
        rawimg=image.copy()
        fetures, faces = self.recognize_face(image)
        id_name="Unknown"
        id_name_list=[]
        if faces is not None:
            for idx, (face, feature) in enumerate(zip(faces, fetures)):
                result, user = self.match(feature)
                box = list(map(int, face[:4]))
                color = (0, 255, 0) if result else (0, 0, 255)
                linethickness = 4
                thickness=2
                cv2.rectangle(image, box, color, thickness, cv2.LINE_AA)
                id_name, score = user if result else (f"Unknown", 0.0)
                
                if id_name=='Unknown':
                    pass
                    #cv2.rectangle(image, (box[0],box[1]-20),(box[0]+150,box[1]) ,(0,0,0), -1, cv2.LINE_AA)
                    #cv2.putText(image, "Unknown", (box[0],box[1]-5), cv2.FONT_HERSHEY_SIMPLEX, .75, color, 2, cv2.LINE_AA)
                else:
                    cv2.rectangle(image, (box[0],box[1]-20),(box[0]+150,box[1]) ,(0,0,0), -1, cv2.LINE_AA)
                    cv2.putText(image, id_name.split('%')[-1], (box[0],box[1]-5), cv2.FONT_HERSHEY_SIMPLEX, .75, color, 2, cv2.LINE_AA)
                id_name_list.append(id_name)
        return id_name_list
    def detect_for_capture(self,image):
        linethickness = 4
        h,w=image.shape[:2]
        x1,y1,x2,y2=int(w/2)-200,int(h/2)-150,int(w/2)+200,int(h/2)+150
        cv2.rectangle(image, (x1,y1-35),(x2,y1), (0,0,0), -1, cv2.LINE_AA)
        cv2.putText(image, "Keep Face Inside Box", (x1,y1-10), cv2.FONT_HERSHEY_COMPLEX_SMALL, 1.5, (255,255,255), 1, cv2.LINE_AA)
        cv2.rectangle(image, (x1,y1),(x2,y2), (0,255,255), linethickness, cv2.LINE_AA)
        fetures, faces = self.recognize_face(image)        
        if faces is not None:
            for idx, (face, feature) in enumerate(zip(faces, fetures)):
                result, user = self.match(feature)
                box = list(map(int, face[:4]))
                color=(0,255,0)
                if box[0]>x1 and box[1]>y1 and box[2]<x2 and box[3]<y2:
                    #cv2.rectangle(image, box, color, linethickness, cv2.LINE_AA)
                    cv2.rectangle(image, (x1,y1),(x2,y2), (0,255,0), linethickness, cv2.LINE_AA)
                    cv2.rectangle(image, (0,0),(1500,80), (0,0,0), -1, cv2.LINE_AA)
                    cv2.putText(image, "You can capture Now", (0,60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0,255,0), 2, cv2.LINE_AA)
                    return True
        
        return False

    



        
