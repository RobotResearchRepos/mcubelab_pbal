#!/usr/bin/env python
import os,sys,inspect
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
sys.path.insert(0,os.path.dirname(os.path.dirname(currentdir)))

import numpy as np
import time

from Modelling.system_params import SystemParams
from Estimation.gtsam_advanced_estimator import gtsam_advanced_estimator
from Helpers.ros_manager import ros_manager
from Helpers.camera_transform_manager import camera_transform_manager
from PlottingandVisualization.system_visualizer import system_visualizer
import Helpers.kinematics_helper as kh
import PlottingandVisualization.image_overlay_helper as ioh
import Estimation.image_segmentation as img_seg
import random

from Estimation.contact_mode_reasoning import contact_mode_reasoning
from Helpers.kinematics_helper import mod2pi

def get_shape_prior(add_noise = False, noise_diameter = 0.0):
    rm = ros_manager()
    rm.spawn_transform_listener()
    rm.subscribe_to_list(['/near_cam/color/image_raw',
                          '/near_cam/color/camera_info',
                          '/ee_pose_in_world_manipulation_from_franka_publisher',
                          '/ee_pose_in_base_from_franka_publisher',
                          '/torque_cone_boundary_test',],True)
    
    ctm = camera_transform_manager(rm,'near')
    ctm.setup_frames()
    camera_transformation_matrix = ctm.generate_camera_transformation_matrix()

    rm.wait_for_necessary_data()
    rm.unpack_all()

    cv_image = rm.near_cam_image_raw

    # vertex_list = img_seg.find_the_object(cv_image,rm.ee_pose_in_world_manipulation_homog,camera_transformation_matrix)
    visited_array = np.zeros([len(cv_image),len(cv_image[0])])
    vertex_list = img_seg.fast_polygon_estimate(cv_image,rm.ee_pose_in_world_manipulation_homog,camera_transformation_matrix,visited_array, is_fine = False, color_dist=28)

    # if add_noise:
    #     for i in range(len(vertex_list)):
    #         for j in range(2):
    #             vertex_list[i][j]+=random.uniform(-noise_diameter,noise_diameter)

    rm.unregister_all()

    return np.vstack(vertex_list).T

if __name__ == '__main__':
    global rospy

    # load params
    node_name = 'gtsam_pivot_estimator'

    sys_params = SystemParams()
    controller_params = sys_params.controller_params
    initial_object_params = sys_params.object_params

    l_contact = initial_object_params['L_CONTACT_MAX']

    RATE = controller_params['RATE']

    use_load = False

    cam_choice = 'near'

    rm = None
    fname = None
    path = None
    if use_load:
        #use if playing from pickle file
        path = '/home/thecube/Documents/pbal_experiments/gtsam_test_data_fall_2022'
        # path = '/home/taylorott/Documents/experiment_data/gtsam_test_data_fall_2022'
        fname = '/test_data-experiment0024.pickle'
        rm = ros_manager(load_mode = True, path=path, fname=fname)

    else:
        #use if running live
        rm = ros_manager()

    if rm.load_mode:
        rm.setRate(RATE)
    else:
        import rospy
        rospy.init_node(node_name)
        rate = rospy.Rate(RATE)

    rm.spawn_transform_listener()

    rm.subscribe_to_list(['/torque_cone_boundary_test',
                          '/torque_cone_boundary_flag',
                          '/sliding_state',
                          '/ee_pose_in_world_manipulation_from_franka_publisher',
                          '/end_effector_sensor_in_world_manipulation_frame',
                          '/end_effector_sensor_in_end_effector_frame',
                          '/friction_parameters',],True)

    rm.subscribe_to_list(['/barrier_func_control_command','/polygon_vision_estimate',],False)

    wall_contact_on = False

    my_cm_reasoner = contact_mode_reasoning(l_contact)


    rm.spawn_publisher_list(['/pivot_frame_estimated','/polygon_contact_estimate'])

    shape_name_list = ['big_triangle','big_square','rectangle','square','triangle','big_rectangle','rectangle_bump_in','rectangle_bump_out']


    hand_front_center = np.array([0.0, 0.0, .041, 1.0])

    # object_vertex_array = get_shape_prior(add_noise = True, noise_diameter = .01)
    object_vertex_array = get_shape_prior(add_noise = False)
    num_vertices = len(object_vertex_array[0])

    print('shape prior acquired')

    rm.wait_for_necessary_data()
    rm.unpack_all()

    object_vertex_array = np.dot(kh.invert_transform_homog(rm.ee_pose_in_world_manipulation_homog),object_vertex_array)

    theta_hand = kh.quatlist_to_theta(rm.ee_pose_in_world_manipulation_list[3:])
    hand_pose_pivot_estimator = np.array([rm.ee_pose_in_world_manipulation_list[0],rm.ee_pose_in_world_manipulation_list[1], theta_hand])

    current_estimator = gtsam_advanced_estimator(object_vertex_array,rm.ee_pose_in_world_manipulation_homog,rm.ee_pose_in_world_manipulation_homog, hand_pose_pivot_estimator)

    current_estimate_dict = current_estimator.generate_estimate_dict()
    my_cm_reasoner.update_previous_estimate(current_estimate_dict)

    print('starting estimator')

    t_vision_recent = time.time()-1.0
    time_since_last_vision_message = 100

    corner_contact_is_feasible = False
    prev_step_was_line_contact = True

    num_line_contact_detected_count = np.inf
    corner_contact_dict = None

    wall_contact_force_margin = 3.0

    while (rm.load_mode and rm.read_still_running()) or (not rm.load_mode and not rospy.is_shutdown()):
        rm.unpack_all()

        can_run_estimate = False

        hand_contact_indices = []
        ground_contact_indices = []
        wall_contact_indices = []
        wall_flag = -1

        
        if len(rm.friction_parameter_dict['aer'])>0:
            wall_contact_right_bool = any(np.dot(rm.friction_parameter_dict['aer'],rm.measured_world_manipulation_wrench) > rm.friction_parameter_dict['ber'] + wall_contact_force_margin)
        else:
            wall_contact_right_bool = True

        if len(rm.friction_parameter_dict['ael'])>0:
            wall_contact_left_bool = any(np.dot(rm.friction_parameter_dict['ael'],rm.measured_world_manipulation_wrench) > rm.friction_parameter_dict['bel'] + wall_contact_force_margin)
        else:
            wall_contact_left_bool = True

        if wall_contact_right_bool and not wall_contact_left_bool:
            wall_flag = 0
        elif not wall_contact_right_bool and wall_contact_left_bool:
            wall_flag = 1
        elif wall_contact_right_bool and wall_contact_left_bool:
            wall_flag = 2

        wall_contact_on = wall_contact_right_bool or wall_contact_left_bool

        # print('wall_contact_on: ',wall_contact_on)

        # if rm.barrier_func_control_command_has_new and rm.command_msg['command_flag']==2:
        #     if rm.command_msg['mode']==0:
        #         wall_contact_on = True
        #     elif rm.command_msg['mode']==1:
        #         wall_contact_on = False
                
        theta_hand = kh.quatlist_to_theta(rm.ee_pose_in_world_manipulation_list[3:])

        hand_pose_pivot_estimator = np.array([rm.ee_pose_in_world_manipulation_list[0],rm.ee_pose_in_world_manipulation_list[1], theta_hand])
        measured_wrench_pivot_estimator = np.array(rm.measured_world_manipulation_wrench)
        measured_wrench_ee = np.array(rm.measured_contact_wrench)

        my_cm_reasoner.update_pose_and_wrench(hand_pose_pivot_estimator,measured_wrench_pivot_estimator,measured_wrench_ee)
        my_cm_reasoner.update_torque_cone_boundary_flag(rm.torque_cone_boundary_test,rm.torque_cone_boundary_flag)
        my_cm_reasoner.COP_reasoning_hand_contact()
        line_line_to_no_contact_check = my_cm_reasoner.update_check_on_transition_from_hand_line_object_line_contact_to_no_contact()

     

        if current_estimator.has_run_once:

            temp_corner_contact_dict = my_cm_reasoner.compute_feasibility_of_hand_line_object_corner_contact()

            if temp_corner_contact_dict['is_feasible']:
                corner_contact_is_feasible = True
                corner_contact_dict = temp_corner_contact_dict
                num_line_contact_detected_count = 0
            else:
                num_line_contact_detected_count+=1
                # print(num_line_contact_detected_count)
                if num_line_contact_detected_count>15:
                    corner_contact_is_feasible = False




        if rm.polygon_vision_estimate_has_new and rm.polygon_vision_estimate_dict is not None:
            t_vision_recent = time.time()
            time_since_last_vision_message = 0.0

            vision_vertex_array = rm.polygon_vision_estimate_dict['vertex_array']
            my_cm_reasoner.update_vision(vision_vertex_array)
            vision_hypothesis_dict = my_cm_reasoner.compute_hypothesis_object_poses_from_vision()
        else:
            time_since_last_vision_message = time.time()-t_vision_recent



        if rm.torque_cone_boundary_test is not None and rm.torque_cone_boundary_test and corner_contact_is_feasible and measured_wrench_ee[0]>3.0:
            can_run_estimate = True
            prev_step_was_line_contact = False

            current_estimator.increment_time()

            current_estimator.add_hand_pose_measurement(hand_pose_pivot_estimator)
            current_estimator.add_hand_wrench_measurement(measured_wrench_pivot_estimator)
            current_estimator.add_sliding_state(rm.sliding_state)
            current_estimator.update_wall_contact_state(wall_contact_on)

            current_estimator.add_kinematic_constraints_object_corner_hand_line_contact(corner_contact_dict)

            hand_contact_indices = [corner_contact_dict['contact_vertex']]

            current_estimator.current_contact_face = None

            kinematic_hypothesis_dict = my_cm_reasoner.compute_hypothesis_object_poses_assuming_no_object_motion()

            if time_since_last_vision_message<.2:

                hypothesis_index = my_cm_reasoner.choose_vision_hypothesis(vision_hypothesis_dict,kinematic_hypothesis_dict)

                if hypothesis_index is not None:
                    current_estimator.add_vision_estimate(vision_vertex_array)
                    current_estimator.add_vision_constraints_no_hand_contact(vision_hypothesis_dict['hypothesis_obj_to_vision_map_list'][hypothesis_index])
        # if False:
        #     pass


        elif rm.torque_cone_boundary_test is not None and rm.torque_cone_boundary_test and measured_wrench_ee[0]>3.0:
            can_run_estimate = True
            

            current_estimator.increment_time()

            current_contact_face, s_current_cm_reasoner = my_cm_reasoner.compute_hand_contact_face()

            current_estimator.current_contact_face = current_contact_face

            if not prev_step_was_line_contact:
                current_estimator.s_current = s_current_cm_reasoner

            current_estimator.add_hand_pose_measurement(hand_pose_pivot_estimator)
            current_estimator.add_hand_wrench_measurement(measured_wrench_pivot_estimator)
            current_estimator.add_sliding_state(rm.sliding_state)
            current_estimator.update_wall_contact_state(wall_contact_on)

            current_estimator.add_kinematic_constraints_hand_flush_contact()


            kinematic_hypothesis_dict = my_cm_reasoner.compute_hypothesis_object_poses_assuming_hand_line_object_line_contact()

            hand_contact_indices = [current_contact_face,(current_contact_face+1)%num_vertices]

            # if rm.polygon_vision_estimate_has_new and rm.polygon_vision_estimate_dict is not None:
            if time_since_last_vision_message<.2:
                hypothesis_index = my_cm_reasoner.choose_vision_hypothesis(vision_hypothesis_dict,kinematic_hypothesis_dict)
                current_estimator.add_vision_estimate(vision_vertex_array)

                if hypothesis_index is not None:
                    current_estimator.add_vision_constraints_hand_flush_contact(vision_hypothesis_dict['hypothesis_obj_to_vision_map_list'][hypothesis_index])
                
            prev_step_was_line_contact = True


        elif rm.polygon_vision_estimate_has_new and rm.polygon_vision_estimate_dict is not None:
            kinematic_hypothesis_dict = my_cm_reasoner.compute_hypothesis_object_poses_assuming_no_object_motion()
            hypothesis_index = my_cm_reasoner.choose_vision_hypothesis(vision_hypothesis_dict,kinematic_hypothesis_dict)

            if hypothesis_index is not None:
       
                prev_step_was_line_contact = False

                can_run_estimate = True
                current_estimator.current_contact_face = None

                current_estimator.increment_time()
                current_estimator.add_hand_pose_measurement(hand_pose_pivot_estimator)
                current_estimator.add_hand_wrench_measurement(measured_wrench_pivot_estimator)
                current_estimator.add_sliding_state(rm.sliding_state)
                current_estimator.update_wall_contact_state(wall_contact_on)

                # current_estimator.initialize_current_object_pose_variables()

                test_val = vision_hypothesis_dict['hypothesis_theta_list'][hypothesis_index]-current_estimator.theta_obj_in_wm_current

                test_val = mod2pi(test_val)



                if current_estimator.has_run_once:
                    current_estimator.add_kinematic_constraints_no_hand_contact_for_vision_assist()

                current_estimator.add_vision_estimate(vision_vertex_array)

                current_estimator.add_vision_constraints_no_hand_contact(vision_hypothesis_dict['hypothesis_obj_to_vision_map_list'][hypothesis_index])

        elif line_line_to_no_contact_check and time_since_last_vision_message>1.0:

            kinematic_hypothesis_dict = my_cm_reasoner.compute_hypothesis_object_poses_assuming_no_contact()

            if kinematic_hypothesis_dict['num_hypothesis'] == 1:
       
                prev_step_was_line_contact = False

                can_run_estimate = True
                current_estimator.current_contact_face = None

                current_estimator.increment_time()
                current_estimator.add_hand_pose_measurement(hand_pose_pivot_estimator)
                current_estimator.add_hand_wrench_measurement(measured_wrench_pivot_estimator)
                current_estimator.add_sliding_state(rm.sliding_state)

                # current_estimator.initialize_current_object_pose_variables()

                current_estimator.add_kinematic_constraints_no_hand_contact_for_no_vision_assist(
                    hypothesis_position = kinematic_hypothesis_dict['hypothesis_object_position_list'][0],
                    hypothesis_theta = kinematic_hypothesis_dict['hypothesis_theta_list'][0],
                    ground_contact_face = kinematic_hypothesis_dict['hypothesis_ground_contact_face_list'][0])


                
        if can_run_estimate:


            hand_front_center_world = np.dot(rm.ee_pose_in_world_manipulation_homog,hand_front_center)


            current_estimate_dict = current_estimator.compute_basic_estimate()
            my_cm_reasoner.update_previous_estimate(current_estimate_dict)
            
            if current_estimate_dict is not None:

                height_indices = np.argsort(current_estimate_dict['vertex_positions_wm_current'][0])

                if current_estimator.contact_vertices is not None:
                    contact_index = current_estimator.contact_vertices[0]
                    pn_wm = current_estimate_dict['vertex_positions_wm_current'][0][contact_index]
                    pt_wm = current_estimate_dict['vertex_positions_wm_current'][1][contact_index]
                    rm.pub_pivot_frame_estimated([pn_wm,pt_wm,hand_front_center_world[2]])

                contact_indices = []
                vertex_array_n = []
                vertex_array_t = []
                vertex_array_z = []

                mgl_cos_theta_list = []
                mgl_sin_theta_list = []

                count = 0
  
                for i in range(len(current_estimate_dict['vertex_positions_wm_current'][0])):
                    
                    vertex_array_n.append(current_estimate_dict['vertex_positions_wm_current'][0][i])
                    vertex_array_t.append(current_estimate_dict['vertex_positions_wm_current'][1][i])
                    vertex_array_z.append(hand_front_center_world[2])

                    mgl_cos_theta_list.append(current_estimate_dict['mglcostheta_current'][i])
                    mgl_sin_theta_list.append(current_estimate_dict['mglsintheta_current'][i])

                    if current_estimator.contact_vertices is not None and i in current_estimator.contact_vertices:
                        contact_indices.append(i)
      
                vertex_array_out = np.array([vertex_array_n,vertex_array_t,vertex_array_z])

                if wall_flag == 0:
                    wall_contact_indices = [np.argmin(vertex_array_out[1])]
                elif wall_flag == 1:
                    wall_contact_indices = [np.argmax(vertex_array_out[1])]

                rm.pub_polygon_contact_estimate(vertex_array_out,contact_indices,mgl_cos_theta_list,mgl_sin_theta_list,
                                                hand_contact_indices = hand_contact_indices,
                                                wall_contact_indices = wall_contact_indices,
                                                wall_flag = wall_flag)


        if rm.load_mode:
            rm.sleep()
        else:
            rate.sleep()

        