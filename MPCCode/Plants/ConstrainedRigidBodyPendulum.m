classdef ConstrainedRigidBodyPendulum
    % A rod of mass (m) and length(l) pivoting about its top end in the
    % gravity plane
    
    properties
        
        % user specified
        m;   % mass (kg)
        l;   % pendulum length (m)
        t_m  % control torque limit (N * m)
        b    % damping coeff
        
        % fixed/derived
        g;              % acceleration due to gravity (kg/m^2)
        I;              % inertia about COM (kg^2 * m^2)
        fmincon_opt;    % options for fmincon
        
        
        % dimensions
        nq;                 % config dimension
        nv;                 % gen.;; gevelocity dimension
        nx;
        nu;                 % input dimension
        neq;                % # of equality const
        niq;                % # of inequality const
        
    end
    
    methods
        
        % initialize
        function obj = ConstrainedRigidBodyPendulum(params)
            
            obj.m = params.m;       % mass  (kg)
            obj.l = params.l;       % length (m)
            obj.t_m = params.t_m;   % control torque limit (N*m)
            obj.b = params.b;       % damping coefficient
            obj.g = params.g;                   % gravity (m/s^2)
            obj.I = obj.l^2 * obj.m^2/12;   % inertia (kg^2 * m^2)
            
            % options for fmincon
            obj.fmincon_opt =  optimoptions('fmincon', 'algorithm', 'sqp', ...
                'display', 'none', 'specifyconstraintgradient', true, ...
                'steptolerance', 1e-8, 'constrainttolerance', 1.e-4, ...
                'maxfunctionevaluations', 2000);
            
            % dimensions
            obj.nq = 3;
            obj.nv = 3;
            obj.nx = obj.nq + obj.nv;
            obj.nu = 3;
            obj.neq = 2;
            obj.niq = 2;
        end
        
        % given xk, find xkp1 and uk (pivot forces; input torque) that
        % that satisfy the following equations:
        % (1) x_{k+1} = xk + dt * obj.dynamics(xk, uk)
        % (2) obj.pivot_const(xk) = 0
        % (3) fix torque (uk(end)) to the value given     
        function [xkp1, uk] =  dynamics_solve(obj, xk, uk, dt)
            
            qk = xk(1:obj.nq);
            qkd = xk(obj.nq + (1:obj.nv));            
            
            % dynamics: x_{k+1} = xk + dt * obj.dynamics(xk, uk)
            M = obj.build_mass_matrix();
            c = obj.build_coriolis_and_potential(qkd);
            B  = obj.build_input_matrix(qk);
            
            Adyn = [eye(6), [zeros(3); dt * -(M\B)]];
            bdyn = xk + dt * [qkd; -(M\c)];
            
            % fix torque to uk(end)
            [Au, bu] = obj.input_const_fmincon([xk; uk]);
            
            [z, ~, exitflag] = fmincon(@(z) 0, [xk; uk], Au, bu, Adyn, bdyn , ...
                [], [], @obj.equality_const_fmincon, obj.fmincon_opt);
            
            if exitflag < 0
                error('Pendulum sim solver failed')
            end
            
            xkp1 = z(1:6);
            uk = z(7:9);
        end
        
        % wrapper for equality constraint for fmincon, used in dynamics_solve
        function [c, ceq, dc, dceq] = equality_const_fmincon(obj, zk)
            
            xk = zk(1:(obj.nq + obj.nv));
            uk = zk(obj.nq + obj.nv + (1:obj.nu));
            [ceq, dc_dxk, dc_duk] = obj.equality_const(xk, uk);
            dceq = [dc_dxk, dc_duk]';
            c = [];
            dc = [];
        end
        
        % contraint that matches uk(end) i.e., the applied torque to what's
        % specified by zk = [xk; uk]
        function [A, b] = input_const_fmincon(obj, zk)
            
            xk = zk(1:(obj.nq + obj.nv));
            uk = zk(obj.nq + obj.nv + (1:obj.nu));
            [c, dc_dx, dc_du] = obj.inequality_const(xk, uk);
            A = [dc_dx, dc_du];
            b = [uk(end); -uk(end)];
            
        end
        
        % continuous forward dynamics
        % [qkd, qkdd] = [qkd; M^{-1} * (B(q) * uk - c(qd))]
        % xk = [qk; qkd]
        function [f, df_dx, df_du] = dynamics(obj, xk, uk)
            
            % separate state
            qk = xk(1:obj.nq);
            qkd = xk(obj.nq + (1:obj.nv));
            
            % build manipulator eqn
            M = obj.build_mass_matrix();
            c = obj.build_coriolis_and_potential(qkd);
            B = obj.build_input_matrix(qk);
            
            % solve for qkdd and integrate
            f = [qkd; M\(B * uk - c)];
            
            % derivative w.r.t. xk
            dc_dqd = [0, 0, 0;
                0, 0, 0;
                0, 0, obj.b];
            
            dBu_dq = [0, 0, 0;
                0, 0, 0
                0, 0, 0.5*obj.l*(sin(qk(3)) * uk(1) - cos(qk(3)) * uk(2))] ;
            
            df_dx =  [zeros(obj.nq), eye(obj.nv); M\dBu_dq ,-M\dc_dqd];
            
            % derivative w.r.t to uk
            df_du = [zeros(obj.nq, obj.nu); (M\B)];
            
        end
        
        % equality constraints, c(x, u) = 0, and first derivatives
        % current we this is the constraint the pin-joint has on the
        % velocity
        function [c, dc_dx, dc_du] = equality_const(obj, xk, uk)            

            tht = xk(3);        % rotation of obj
            qd = xk(obj.nq + (1:obj.nv));               % velocity of COM            

            % pivot const on velocity
            dphi_dq = [1, 0, -0.5 * obj.l * cos(tht);
                0, 1, - 0.5 * obj.l * sin(tht)];            
            c = dphi_dq * qd;
            
            dc_dx = [ [0, 0, 0.5 * obj.l * sin(tht) * qd(3);
                0, 0, -0.5 * obj.l * cos(tht) * qd(3)], dphi_dq];

            dc_du = zeros(obj.neq, obj.nu);
            
        end
        
        % inequality constraints, c(x, u) <= 0, and first derivatives
        % currently constraints uk(end) i.e., the torque to be -t_m <= tau <= t_m
        function [c, dc_dx, dc_du] = inequality_const(obj, xk, uk)
            c = [uk(end); -uk(end)] - [obj.t_m; obj.t_m];
            dc_dx = zeros(obj.niq, obj.nx);
            dc_du = [0, 0, 1; 0, 0, -1];
        end
                
        % measure the difference between two state vectors
        function dx = state_diff(obj, x1, x2)
            d = mod(x1(1) - x2(1) + pi, 2*pi) - pi;
            dx = [d; x1(2:end) - x2(2:end)];
        end
        
        %%%%%%%% Helper Functions %%%%%%%%%%%
        
        % B(q) in M(q) qdd + c(qd) = B(q) * u
        function B = build_input_matrix(obj, qk)            
            tht = qk(3);            
            B = [1, 0, 0;
                0, 1, 0;
                -0.5 * obj.l * cos(tht), -0.5 * obj.l * sin(tht), 1];
        end
        
        % M(q) in M(q) qdd + c(qd) = B(q) * u
        function M = build_mass_matrix(obj)
            M = [obj.m, 0, 0;
                0, obj.m, 0;
                0, 0, obj.I];
        end        
                
        % c(qd) in M*qdd + c(qd) = B(q) * u
        function c = build_coriolis_and_potential(obj, qkd)
            c = [0; obj.m * obj.g; 0] + [0; 0; obj.b*qkd(3)];
        end

    end
end
