import os,sys,inspect
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
gparentdir = os.path.dirname(parentdir)
sys.path.insert(0,parentdir) 
sys.path.insert(0,gparentdir)

import argparse
from cv_bridge import CvBridge
import json
import pdb
import pickle
import rosbag

import Helpers.pbal_msg_helper as pmh


# def argument_parser():
#     parser = argparse.ArgumentParser(description='')

#     # experiment setup
#     parser.add_argument('bagfile_name', default="", type=str,
#                         help='name of bag file to load')

#     args = parser.parse_args()

#     return args

# def parse_json_string(msg):
#     return json.loads(msg.data)


def parse_wrench_stamped(msg):
    return [
        msg.wrench.force.x, msg.wrench.force.y, msg.wrench.force.z, 
        msg.wrench.torque.x, msg.wrench.torque.y, msg.wrench.torque.z]

def parse_pose_stamped(msg):
    return [
        msg.pose.position.x, msg.pose.position.y, msg.pose.position.z, 
        msg.pose.orientation.x, msg.pose.orientation.y, msg.pose.orientation.z,
        msg.pose.orientation.w]

def parse_transform_stamped(msg):
    return [
        msg.transform.translation.x, msg.transform.translation.y, msg.transform.translation.z, 
        msg.transform.rotation.x, msg.transform.rotation.y, msg.transform.rotation.z,
        msg.transform.rotation.w]

def parse_custom_pbal_message(msg):

    if 'SlidingStateStamped' in msg._type:
        msg = pmh.sliding_stamped_to_sliding_dict(msg)

    elif 'QPDebugStamped' in msg._type:
        msg = pmh.qp_debug_stamped_to_qp_debug_dict(msg)

    elif 'FrictionParamsStamped' in msg._type:
        msg = pmh.friction_stamped_to_friction_dict(msg)

    elif 'ControlCommandStamped' in msg._type:
        msg = pmh.command_stamped_to_command_dict(msg)
    else:
        msg = None

    return msg

def parse_apriltag_detection_Int32(msg):
    msg = msg.data

def parse_apriltag_detection_Bool(msg):
    msg = msg.data
    
def parse_apriltag_detection_array(msg_in):

    

    if len(msg_in.detections)>0:
        detection_dict = {}
        for i in range(len(msg_in.detections)):

            msg = msg_in.detections[i]
            
            detection_dict[msg.id[0]] = {
            'id': msg.id[0],
            'size': msg.size[0],
            'position': [msg.pose.pose.pose.position.x, msg.pose.pose.pose.position.y, 
                msg.pose.pose.pose.position.z],
            'orientation': [msg.pose.pose.pose.orientation.x, msg.pose.pose.pose.orientation.y, 
                msg.pose.pose.pose.orientation.z, msg.pose.pose.pose.orientation.w]
            }
        return detection_dict
    else:
        return None
msg_types = []
if __name__ == "__main__":

    # args = argument_parser()
    # bagfile_name = args.bagfile_name
    # bagfile_name = '2022-06-22-23-13-19-test_data-experiment0001.bag'

    dir_save_bagfile = '/home/thecube/Documents/pbal_experiments/gtsam_test_data'
    # dir_save_bagfile = os.environ['CODE_BASE'] + '/data/rosbag_data/'


    pickle_dict = {}

    for fname in os.listdir(dir_save_bagfile):
        fname_list = fname.split('.')
        if fname_list[1]=='pickle':
            pickle_dict[fname_list[0]]=True

    unpickled_list = []
    for fname in os.listdir(dir_save_bagfile):
        fname_list = fname.split('.')
        if fname_list[1]=='bag' and fname_list[0] not in pickle_dict:
            unpickled_list.append(fname)

    for bagfile_name in unpickled_list:
        fpath = os.path.join(dir_save_bagfile, bagfile_name)
        print('Loading: ' + bagfile_name)

        # build data structure
        bridge = CvBridge()
        data = {}
        
        # fill out topics
        with rosbag.Bag(fpath, 'r') as bag:
            for topic, msg, time, in bag.read_messages():

                if msg._type not in msg_types:
                    msg_types.append(msg._type)

                # parse topic by message type            
                if msg._type == 'geometry_msgs/WrenchStamped':
                    msg = parse_wrench_stamped(msg)
                
                elif msg._type == 'geometry_msgs/PoseStamped':
                    msg = parse_pose_stamped(msg)
                
                elif msg._type == 'geometry_msgs/TransformStamped':
                    msg = parse_transform_stamped(msg)
                
                elif msg._type == 'std_msgs/Float32MultiArray':
                    msg = msg.data
                
                elif msg._type == 'sensor_msgs/Image':
                    msg = bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
                           
                elif msg._type == 'apriltag_ros/AprilTagDetectionArray':
                    msg = parse_apriltag_detection_array(msg)

                elif msg._type == 'std_msgs/Int32':
                    msg = parse_apriltag_detection_Int32(msg)

                elif msg._type == 'std_msgs/Bool':
                    msg = parse_apriltag_detection_Bool(msg)

                elif 'pbal/' in msg._type:
                    msg = parse_custom_pbal_message(msg)
                    if msg is None:
                        continue

                # add to data
                if not (topic[1:] in data):
                    print(topic[1:])
                    data[topic[1:]] = [{'time': time.to_sec(), 'msg': msg}]
                else:
                    data[topic[1:]].extend([{'time': time.to_sec(), 'msg': msg}])
                

        print(msg_types)

        print('Saving: ' + os.path.splitext(bagfile_name)[0] + '.pickle')
        spath = os.path.join(dir_save_bagfile, 
            os.path.splitext(bagfile_name)[0])

        with open(spath + '.pickle', 'wb') as handle:
            pickle.dump(data, handle, protocol=pickle.HIGHEST_PROTOCOL)

        with open(spath + '.pickle', 'rb') as handle:
            b = pickle.load(handle)

    # # pdb.set_trace()